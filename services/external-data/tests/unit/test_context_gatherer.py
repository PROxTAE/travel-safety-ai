"""The fan-out behind `/internal/v1/context/query`.

No HTTP and no providers here - only the orchestration, which is where the
dangerous bugs live. Three properties, each with a failure that would be hard
to spot in production:

A slow capability that sinks the whole request turns a hazard check into a
timeout. A capability quietly missing from the answer is indistinguishable from
"nothing to report", which for hazards is the opposite answer. And a cancelled
caller recorded as a provider failure would open a circuit breaker against a
provider that never did anything wrong.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.domain.enums import ProviderKind
from app.domain.errors import ProviderError, ProviderErrorCode
from app.services.context import (
    CapabilityCall,
    ContextGatherer,
    Outcome,
)


class _FakeAdapters:
    """The gatherer only reaches for adapters when grouping duplicates."""

    def all_for_kind(self, kind: ProviderKind) -> list[Any]:
        return []

    def blocked_reason(self, kind: ProviderKind) -> str:
        return "no provider"

    def get(self, provider_id: str) -> Any:
        return None


def _gatherer(max_concurrency: int = 4) -> ContextGatherer:
    return ContextGatherer(_FakeAdapters(), max_concurrency=max_concurrency)  # type: ignore[arg-type]


def _answers(
    records: list[Any], providers: list[str], *, delay: float = 0.0
) -> CapabilityCall:
    async def call(budget: float) -> tuple[list[Any], list[str]]:
        if delay:
            await asyncio.sleep(delay)
        return records, providers

    return call


def _raises(error: BaseException, *, delay: float = 0.0) -> CapabilityCall:
    async def call(budget: float) -> tuple[list[Any], list[str]]:
        if delay:
            await asyncio.sleep(delay)
        raise error

    return call


def _never_finishes() -> CapabilityCall:
    async def call(budget: float) -> tuple[list[Any], list[str]]:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    return call


# ------------------------------------------------------------ concurrency


async def test_capabilities_run_concurrently_not_one_after_another() -> None:
    """Four capabilities of 200 ms each must cost about 200 ms, not 800.

    Sequentially a global query cost the sum of its providers, so one slow
    source made every answer late.
    """
    plan: dict[ProviderKind, CapabilityCall] = {
        kind: _answers([kind], [str(kind)], delay=0.2)
        for kind in (
            ProviderKind.WEATHER,
            ProviderKind.DISASTER,
            ProviderKind.ROUTE,
            ProviderKind.EMERGENCY_DIRECTORY,
        )
    }
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await _gatherer().gather(plan, deadline_seconds=10)
    elapsed = loop.time() - started

    assert elapsed < 0.6, f"took {elapsed:.2f}s; capabilities are running in series"
    assert all(
        capability.outcome is Outcome.ANSWERED
        for capability in result.capabilities.values()
    )


async def test_concurrency_is_bounded() -> None:
    """The per-provider limiter is the real guard, but the fan-out itself must
    not become a burst against a free-tier account."""
    in_flight = 0
    peak = 0

    def _tracked() -> CapabilityCall:
        async def call(budget: float) -> tuple[list[Any], list[str]]:
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return [], []

        return call

    plan = {
        kind: _tracked()
        for kind in (
            ProviderKind.WEATHER,
            ProviderKind.DISASTER,
            ProviderKind.ROUTE,
            ProviderKind.EMERGENCY_DIRECTORY,
        )
    }
    await _gatherer(max_concurrency=2).gather(plan, deadline_seconds=10)

    assert peak <= 2, f"{peak} capabilities were in flight at once"


# --------------------------------------------------------------- deadline


async def test_a_slow_capability_is_cut_and_the_rest_still_answer() -> None:
    """The property that matters most.

    A traveller waiting on a hazard check should not lose the weather because a
    routing provider is slow.
    """
    plan: dict[ProviderKind, CapabilityCall] = {
        ProviderKind.WEATHER: _answers(["forecast"], ["open_meteo_forecast"]),
        ProviderKind.ROUTE: _never_finishes(),
    }
    result = await _gatherer().gather(plan, deadline_seconds=1)

    assert result.capabilities[ProviderKind.WEATHER].outcome is Outcome.ANSWERED
    assert result.records(ProviderKind.WEATHER) == ["forecast"]
    assert result.capabilities[ProviderKind.ROUTE].outcome is Outcome.TIMED_OUT
    assert "ROUTE" in result.degraded_services


async def test_the_whole_request_respects_one_deadline() -> None:
    plan: dict[ProviderKind, CapabilityCall] = {
        ProviderKind.DISASTER: _never_finishes(),
        ProviderKind.ROUTE: _never_finishes(),
    }
    loop = asyncio.get_running_loop()
    started = loop.time()
    await _gatherer().gather(plan, deadline_seconds=1)
    elapsed = loop.time() - started

    assert elapsed < 2.0, f"took {elapsed:.2f}s against a 1s budget"


async def test_a_capability_queued_behind_others_does_not_get_a_fresh_budget() -> None:
    """The clock starts at the request, not when a concurrency slot frees up.

    Otherwise a capability that waited behind three others would then be handed
    a full budget of its own and blow the overall deadline.
    """
    plan: dict[ProviderKind, CapabilityCall] = {
        ProviderKind.WEATHER: _never_finishes(),
        ProviderKind.DISASTER: _never_finishes(),
    }
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await _gatherer(max_concurrency=1).gather(plan, deadline_seconds=1)
    elapsed = loop.time() - started

    assert elapsed < 2.0, f"took {elapsed:.2f}s; the second capability restarted the clock"
    assert all(
        capability.outcome is Outcome.TIMED_OUT
        for capability in result.capabilities.values()
    )


# ------------------------------------------------------ what gets reported


async def test_every_requested_capability_appears_in_the_result() -> None:
    plan: dict[ProviderKind, CapabilityCall] = {
        ProviderKind.WEATHER: _answers([], []),
        ProviderKind.DISASTER: _raises(
            ProviderError(ProviderErrorCode.PROVIDER_OUTAGE, "gdacs", message="down")
        ),
        ProviderKind.ROUTE: _never_finishes(),
    }
    result = await _gatherer().gather(plan, deadline_seconds=1)

    assert set(result.capabilities) == {
        ProviderKind.WEATHER,
        ProviderKind.DISASTER,
        ProviderKind.ROUTE,
    }


async def test_a_capability_that_was_not_asked_is_still_named() -> None:
    """An absent key is indistinguishable from "nothing to report", and for
    hazards those are opposite answers."""
    result = await _gatherer().gather(
        {ProviderKind.WEATHER: _answers([], [])},
        deadline_seconds=5,
        skipped=[ProviderKind.DISASTER, ProviderKind.ROUTE],
    )

    assert result.capabilities[ProviderKind.DISASTER].outcome is Outcome.NOT_REQUESTED
    assert result.capabilities[ProviderKind.ROUTE].outcome is Outcome.NOT_REQUESTED


async def test_outside_coverage_is_not_a_degradation() -> None:
    """"This source publishes nothing about that" is not a failure.

    Counting it as degraded would mark the list on nearly every request, and a
    field that is always set stops carrying information.
    """
    plan: dict[ProviderKind, CapabilityCall] = {
        ProviderKind.ROUTE: _raises(
            ProviderError(
                ProviderErrorCode.OUTSIDE_COVERAGE,
                "openrouteservice",
                message="TRAIN is not a road-network mode",
            )
        )
    }
    result = await _gatherer().gather(plan, deadline_seconds=5)

    capability = result.capabilities[ProviderKind.ROUTE]
    assert capability.outcome is Outcome.NOT_COVERED
    assert capability.degraded is False
    assert result.degraded_services == []
    # The provider's own words about coverage help the caller.
    assert "road-network" in (capability.reason or "")


async def test_a_provider_failure_does_not_leak_why_it_failed() -> None:
    """A coverage answer is safe to repeat; a failure message may name a
    credential or an upstream that the caller must not learn about."""
    plan: dict[ProviderKind, CapabilityCall] = {
        ProviderKind.WEATHER: _raises(
            ProviderError(
                ProviderErrorCode.PROVIDER_AUTH,
                "open_meteo_forecast",
                message="Invalid API key abc123secret",
            )
        )
    }
    result = await _gatherer().gather(plan, deadline_seconds=5)

    capability = result.capabilities[ProviderKind.WEATHER]
    assert capability.outcome is Outcome.FAILED
    assert "abc123secret" not in (capability.reason or "")
    assert capability.degraded is True


# ------------------------------------------------------------ cancellation


async def test_a_bug_in_our_own_code_is_not_reported_as_a_degraded_provider() -> None:
    """Recording it as "that source is a bit degraded" would hide a real defect
    behind a partial success."""
    plan: dict[ProviderKind, CapabilityCall] = {
        ProviderKind.WEATHER: _raises(ZeroDivisionError("bug")),
    }
    with pytest.raises(ZeroDivisionError):
        await _gatherer().gather(plan, deadline_seconds=5)


async def test_cancelling_the_caller_cancels_the_fan_out() -> None:
    """When the client goes away, the work must stop rather than run on against
    a quota nobody is waiting for."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def call(budget: float) -> tuple[list[Any], list[str]]:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("unreachable")

    task = asyncio.create_task(
        _gatherer().gather({ProviderKind.WEATHER: call}, deadline_seconds=30)
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


# --------------------------------------------------------------- reporting


async def test_answering_providers_are_listed_for_attribution() -> None:
    """Attribution is a licence obligation, so it has to follow the records."""
    plan: dict[ProviderKind, CapabilityCall] = {
        ProviderKind.WEATHER: _answers(["x"], ["open_meteo_forecast"]),
        ProviderKind.ROUTE: _answers(["y"], ["openrouteservice"]),
    }
    result = await _gatherer().gather(plan, deadline_seconds=5)

    assert set(result.answering_providers) == {
        "open_meteo_forecast",
        "openrouteservice",
    }


async def test_a_deadline_outside_the_allowed_range_is_clamped() -> None:
    plan: dict[ProviderKind, CapabilityCall] = {ProviderKind.WEATHER: _never_finishes()}
    loop = asyncio.get_running_loop()
    started = loop.time()
    await _gatherer().gather(plan, deadline_seconds=0.001)
    assert loop.time() - started >= 1.0, "a sub-second deadline should clamp up to 1s"
