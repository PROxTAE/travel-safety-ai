"""Combined context gathering - the fan-out behind `/internal/v1/context/query`.

Module plan Phase 6: fan out independent calls with bounded concurrency,
combine canonical records and provider health **without deciding risk**, and
propagate cancellation under one overall deadline.

Three properties this module exists to hold.

**A slow capability must not sink the request.** Each capability gets its own
slice of the deadline. One that overruns is cancelled and reported as timed
out; everything that finished is still returned. Sequentially a global query
took as long as the sum of its providers, and a single hanging source made the
whole answer late.

**A capability that could not answer is named, never silently omitted.** An
absent key in the response would be indistinguishable from "there was nothing
to report", and for hazards those are opposite answers.

**Nothing here decides anything.** This module concatenates records and reports
what each source said. Reconciling them is module 05 (`IntegratedTravelContext`
in shared context § 7 step 5); judging them is 06/07. Even the duplicate groups
below are annotations, not merges.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.adapters.factory import AdapterRegistry
from app.domain.enums import ProviderKind
from app.domain.errors import ProviderError, ProviderErrorCode
from app.observability.logging import get_logger
from app.observability.metrics import context_capabilities, source_disagreements
from app.services.dedup import find_duplicate_groups

log = get_logger(__name__)

# Enough to keep every capability in flight at once without turning one request
# into a burst against a free-tier provider. The per-provider concurrency
# limiter in the transport is the real guard; this bounds the fan-out itself.
DEFAULT_MAX_CONCURRENCY = 4

# The transport's own budget is 10s per provider call. Leaving a little room
# above it means a capability normally fails on its own terms - with a typed
# provider error naming what went wrong - rather than being cut off here with
# no explanation.
DEFAULT_DEADLINE_SECONDS = 25.0
MIN_DEADLINE_SECONDS = 1.0
MAX_DEADLINE_SECONDS = 60.0


class Outcome(StrEnum):
    ANSWERED = "ANSWERED"
    # The provider answered and said this query is not something it covers.
    # Distinct from a failure: nobody publishes it, so nobody failed.
    NOT_COVERED = "NOT_COVERED"
    # No usable provider: no credential, not approved, or none configured.
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    NOT_REQUESTED = "NOT_REQUESTED"


@dataclass(slots=True)
class CapabilityResult:
    kind: ProviderKind
    outcome: Outcome
    records: list[Any] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    reason: str | None = None
    elapsed_seconds: float | None = None

    @property
    def degraded(self) -> bool:
        """Degraded means "we should have been able to answer and could not".

        A capability nobody configured, or one that honestly does not cover the
        question, is not a degradation - marking it so would light up the
        degraded list on every request and stop the field meaning anything.
        """
        return self.outcome in (Outcome.FAILED, Outcome.TIMED_OUT)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capability": str(self.kind),
            "outcome": str(self.outcome),
            "providers": self.providers,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.elapsed_seconds is not None:
            payload["elapsed_seconds"] = round(self.elapsed_seconds, 3)
        return payload


@dataclass(slots=True)
class ContextResult:
    capabilities: dict[ProviderKind, CapabilityResult]
    duplicate_groups: list[Any] = field(default_factory=list)

    def records(self, kind: ProviderKind) -> list[Any]:
        result = self.capabilities.get(kind)
        return result.records if result is not None else []

    @property
    def degraded_services(self) -> list[str]:
        names: list[str] = []
        for result in self.capabilities.values():
            if result.degraded:
                names.extend(result.providers or [str(result.kind)])
        return names

    @property
    def answering_providers(self) -> list[str]:
        names: list[str] = []
        for result in self.capabilities.values():
            if result.outcome is Outcome.ANSWERED:
                names.extend(result.providers)
        return names


CapabilityCall = Callable[[float], Awaitable[tuple[list[Any], list[str]]]]


class ContextGatherer:
    """Runs the requested capabilities concurrently under one deadline."""

    def __init__(
        self,
        adapters: AdapterRegistry,
        *,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        self._adapters = adapters
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def gather(
        self,
        plan: dict[ProviderKind, CapabilityCall],
        *,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        skipped: list[ProviderKind] | None = None,
    ) -> ContextResult:
        budget = max(MIN_DEADLINE_SECONDS, min(deadline_seconds, MAX_DEADLINE_SECONDS))
        kinds = list(plan)

        results = await asyncio.gather(
            *(self._run(kind, plan[kind], budget) for kind in kinds),
            return_exceptions=True,
        )

        capabilities: dict[ProviderKind, CapabilityResult] = {}
        for kind, result in zip(kinds, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                # The caller went away. That is not a provider problem and must
                # not be recorded as one - propagate it.
                raise result
            if isinstance(result, BaseException):
                # A bug in our own code. Recording it as "that source is a bit
                # degraded" would hide it behind a partial success.
                raise result
            capabilities[kind] = result

        for kind in skipped or ():
            capabilities.setdefault(
                kind,
                CapabilityResult(
                    kind=kind,
                    outcome=Outcome.NOT_REQUESTED,
                    reason="not requested and nothing in the query implied it",
                ),
            )

        for result in capabilities.values():
            context_capabilities.labels(
                capability=str(result.kind), outcome=str(result.outcome).lower()
            ).inc()

        return ContextResult(
            capabilities=capabilities,
            duplicate_groups=self._group_duplicates(capabilities),
        )

    async def _run(
        self, kind: ProviderKind, call: CapabilityCall, budget: float
    ) -> CapabilityResult:
        loop = asyncio.get_running_loop()
        started = loop.time()

        try:
            async with self._semaphore:
                # The clock starts at the request, not at the moment a slot frees
                # up: a capability that waited behind three others must not then
                # get a fresh full budget and blow the overall deadline.
                remaining = budget - (loop.time() - started)
                if remaining <= 0:
                    return CapabilityResult(
                        kind=kind,
                        outcome=Outcome.TIMED_OUT,
                        reason="the request deadline passed while waiting to start",
                        elapsed_seconds=loop.time() - started,
                    )
                records, providers = await asyncio.wait_for(call(remaining), timeout=remaining)
        except TimeoutError:
            log.warning("context_capability_timeout", capability=str(kind))
            return CapabilityResult(
                kind=kind,
                outcome=Outcome.TIMED_OUT,
                reason=f"no answer within {budget:.0f}s",
                elapsed_seconds=loop.time() - started,
            )
        except ProviderError as error:
            outcome = (
                Outcome.NOT_COVERED
                if error.code is ProviderErrorCode.OUTSIDE_COVERAGE
                else Outcome.FAILED
            )
            if outcome is Outcome.FAILED:
                log.warning(
                    "context_capability_failed",
                    capability=str(kind),
                    error_code=str(error.code),
                )
            return CapabilityResult(
                kind=kind,
                outcome=outcome,
                # The provider's own words about coverage are useful to a caller;
                # its words about a failure are not, and may name a credential.
                reason=error.message if outcome is Outcome.NOT_COVERED else str(error.code),
                elapsed_seconds=loop.time() - started,
            )

        return CapabilityResult(
            kind=kind,
            outcome=Outcome.ANSWERED,
            records=records,
            providers=providers,
            elapsed_seconds=loop.time() - started,
        )

    def _group_duplicates(self, capabilities: dict[ProviderKind, CapabilityResult]) -> list[Any]:
        """Annotate hazards that look like the same event in two sources.

        Grouped, never merged. Every record is still returned; module 05 decides
        which of a pair to believe, and it cannot decide about records it never
        received.
        """
        disasters = capabilities.get(ProviderKind.DISASTER)
        if disasters is None or not disasters.records:
            return []

        groups = find_duplicate_groups(disasters.records)
        if groups:
            source_disagreements.labels(capability=str(ProviderKind.DISASTER)).inc(len(groups))
        return groups
