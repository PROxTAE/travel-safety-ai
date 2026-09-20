"""Periodic health probing.

What this protects: `/internal/v1/providers/health` answering `UNKNOWN` forever
for a provider that is perfectly healthy but served entirely from cache — and
the mirror case, a provider that went down between requests keeping its last
good reading until someone happens to call it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import respx

from app.domain.enums import HealthState, ProviderStatus
from app.providers.registry import Defaults, ResolvedRegistry, load_registry
from app.services.health_probe import ProviderHealthProbe
from app.settings import get_settings
from app.transport.http import ProviderTransport
from tests.conftest import REGISTRY_PATH

GEOCODE_PROBE = "https://geocoding-api.open-meteo.com/v1/search"
USGS_PROBE = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.geojson"
)


class _Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    async def upsert_health(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append(kwargs)


def _probe(
    recorder: _Recorder, *, interval: float = 0.0
) -> tuple[ProviderHealthProbe, ProviderTransport]:
    registry = ResolvedRegistry(load_registry(REGISTRY_PATH), get_settings())
    defaults = Defaults()
    defaults.retry.initial_backoff_seconds = 0.001
    transport = ProviderTransport(defaults)
    return (
        ProviderHealthProbe(
            registry, transport, recorder, interval_seconds=interval
        ),
        transport,
    )


def _state_for(recorder: _Recorder, provider_id: str) -> HealthState:
    return next(
        call["state"] for call in recorder.calls if call["provider_id"] == provider_id
    )


# ------------------------------------------------------------------- targets


def test_only_callable_providers_with_a_probe_url_are_targeted() -> None:
    """A blocked provider is not probed: its state is already known from
    configuration, and calling a provider the Lead has not approved is the
    exact thing the registry gate exists to prevent."""
    probe, _ = _probe(_Recorder())
    ids = {provider.id for provider in probe.targets()}

    assert ids == {
        "open_meteo_geocoding",
        "open_meteo_forecast",
        "usgs_earthquake",
        "gdacs",
        "nasa_eonet",
        # The registered transit feed is keyless, so it is ACTIVE on a bare
        # checkout and probed like the rest.
        "gtfs_registry",
    }
    # openrouteservice declares a health URL but is PENDING_CREDENTIAL.
    assert "openrouteservice" not in ids
    # amadeus has neither.
    assert "amadeus" not in ids


def test_every_target_is_active() -> None:
    probe, _ = _probe(_Recorder())
    for provider in probe.targets():
        assert provider.effective_status is ProviderStatus.ACTIVE
        assert provider.entry.health.url


# -------------------------------------------------------------------- results


@respx.mock
async def test_a_healthy_provider_is_recorded_up_with_latency() -> None:
    respx.get().mock(return_value=httpx.Response(200, json={"ok": True}))
    recorder = _Recorder()
    probe, transport = _probe(recorder)

    results = await probe.probe_once()

    assert set(results.values()) == {HealthState.UP}
    assert len(recorder.calls) == len(results)
    for call in recorder.calls:
        assert call["state"] is HealthState.UP
        assert isinstance(call["latency_ms"], int)
        assert call["reason"] is None
    await transport.aclose()


@respx.mock
async def test_an_outage_is_recorded_down() -> None:
    respx.get().mock(return_value=httpx.Response(503))
    recorder = _Recorder()
    probe, transport = _probe(recorder)

    results = await probe.probe_once()

    assert set(results.values()) == {HealthState.DOWN}
    assert all(call["reason"] for call in recorder.calls)
    await transport.aclose()


@respx.mock
async def test_an_auth_failure_is_not_configured_not_down() -> None:
    """Our key being wrong is not the provider being unhealthy."""
    respx.get().mock(return_value=httpx.Response(401))
    recorder = _Recorder()
    probe, transport = _probe(recorder)

    assert set((await probe.probe_once()).values()) == {HealthState.NOT_CONFIGURED}
    await transport.aclose()


@respx.mock
async def test_an_unexpected_status_is_degraded_not_up() -> None:
    """Reachable but not answering as documented is neither healthy nor down."""
    respx.get(GEOCODE_PROBE).mock(return_value=httpx.Response(204))
    respx.get().mock(return_value=httpx.Response(200, json={"ok": True}))
    recorder = _Recorder()
    probe, transport = _probe(recorder)

    results = await probe.probe_once()

    assert results["open_meteo_geocoding"] is HealthState.DEGRADED
    reason = next(
        call["reason"]
        for call in recorder.calls
        if call["provider_id"] == "open_meteo_geocoding"
    )
    assert "expected HTTP 200" in reason
    await transport.aclose()


@respx.mock
async def test_one_provider_failing_does_not_stop_the_pass() -> None:
    """A single unreachable source must not cost us the readings for the rest."""
    respx.get(USGS_PROBE).mock(return_value=httpx.Response(503))
    respx.get().mock(return_value=httpx.Response(200, json={"ok": True}))
    recorder = _Recorder()
    probe, transport = _probe(recorder)

    results = await probe.probe_once()

    assert results["usgs_earthquake"] is HealthState.DOWN
    assert _state_for(recorder, "gdacs") is HealthState.UP
    assert len(recorder.calls) == len(probe.targets())
    await transport.aclose()


@respx.mock
async def test_a_failing_recorder_does_not_break_the_pass() -> None:
    """The observation is a side effect; losing the database must not stop the
    service from checking on its providers."""
    respx.get().mock(return_value=httpx.Response(200, json={"ok": True}))
    probe, transport = _probe(_Recorder(fail=True))

    assert set((await probe.probe_once()).values()) == {HealthState.UP}
    await transport.aclose()


# ------------------------------------------------------------------ lifecycle


def test_a_zero_interval_disables_the_probe() -> None:
    probe, _ = _probe(_Recorder(), interval=0.0)
    assert probe.enabled is False

    probe.start()  # must be a no-op, not an error
    assert probe._task is None


@respx.mock
async def test_the_loop_probes_immediately_then_repeats() -> None:
    """Waiting a full interval before the first pass would leave a freshly
    booted service reporting UNKNOWN for minutes."""
    respx.get().mock(return_value=httpx.Response(200, json={"ok": True}))
    recorder = _Recorder()
    probe, transport = _probe(recorder, interval=0.05)

    probe.start()
    assert probe.enabled is True
    await asyncio.sleep(0.12)
    first_pass = len(recorder.calls)
    await probe.stop()

    assert first_pass >= len(probe.targets())  # at least one complete pass
    await transport.aclose()


@respx.mock
async def test_stopping_is_clean_and_idempotent() -> None:
    respx.get().mock(return_value=httpx.Response(200, json={"ok": True}))
    probe, transport = _probe(_Recorder(), interval=0.05)

    probe.start()
    await asyncio.sleep(0.01)
    await probe.stop()
    await probe.stop()  # must not raise on a second call

    assert probe._task is None
    await transport.aclose()


async def test_stopping_a_probe_that_never_started_is_fine() -> None:
    probe, _ = _probe(_Recorder(), interval=0.0)
    await probe.stop()


@pytest.mark.parametrize("interval", [0.0, -1.0])
def test_non_positive_intervals_are_disabled(interval: float) -> None:
    probe, _ = _probe(_Recorder(), interval=interval)
    assert probe.enabled is False
