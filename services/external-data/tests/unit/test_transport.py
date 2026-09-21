"""Shared transport: retry, deadline, circuit breaker and the SSRF guard.

These behaviours are the reason adapters are thin. If the transport gets them
wrong, every adapter is wrong in the same way.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.domain.enums import ProviderStatus
from app.domain.errors import ProviderError, ProviderErrorCode
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderTransport
from app.transport.resilience import CircuitState
from tests.conftest import REGISTRY_PATH

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


def _provider(provider_id: str = "open_meteo_geocoding") -> ResolvedProvider:
    registry = load_registry(REGISTRY_PATH)
    entry = next(p for p in registry.providers if p.id == provider_id)
    settings = get_settings()
    return ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=settings.base_url_for(entry.base_url_env),
    )


def _transport(**defaults_kwargs: object) -> ProviderTransport:
    defaults = Defaults(**defaults_kwargs)  # type: ignore[arg-type]
    defaults.retry.initial_backoff_seconds = 0.001  # keep the suite fast
    return ProviderTransport(defaults)


@respx.mock
async def test_successful_request_returns_payload_and_fetch_time() -> None:
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(200, json={"results": [{"id": 1}]}))
    transport = _transport()
    response = await transport.request(_provider(), "/v1/search", params={"name": "X"})

    assert response.status_code == 200
    assert response.payload == {"results": [{"id": 1}]}
    assert response.fetched_at > 0
    await transport.aclose()


@respx.mock
async def test_429_is_retried_and_honours_retry_after() -> None:
    route = respx.get(GEOCODE_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    transport = _transport()
    response = await transport.request(_provider(), "/v1/search")

    assert route.call_count == 2
    assert response.payload == {"ok": True}
    await transport.aclose()


@respx.mock
async def test_401_is_not_retried_and_maps_to_provider_auth() -> None:
    """Retrying an auth failure only burns quota - the key will not fix itself."""
    route = respx.get(GEOCODE_URL).mock(return_value=httpx.Response(401))
    transport = _transport()

    with pytest.raises(ProviderError) as excinfo:
        await transport.request(_provider(), "/v1/search")

    assert excinfo.value.code is ProviderErrorCode.PROVIDER_AUTH
    assert route.call_count == 1
    await transport.aclose()


@respx.mock
async def test_404_maps_to_outside_coverage() -> None:
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(404))
    transport = _transport()

    with pytest.raises(ProviderError) as excinfo:
        await transport.request(_provider(), "/v1/search")

    assert excinfo.value.code is ProviderErrorCode.OUTSIDE_COVERAGE
    await transport.aclose()


@respx.mock
async def test_timeout_maps_to_provider_timeout_and_is_retried() -> None:
    route = respx.get(GEOCODE_URL).mock(side_effect=httpx.ConnectTimeout("too slow"))
    transport = _transport()

    with pytest.raises(ProviderError) as excinfo:
        await transport.request(_provider(), "/v1/search")

    assert excinfo.value.code is ProviderErrorCode.PROVIDER_TIMEOUT
    assert route.call_count == 3  # default max_attempts
    await transport.aclose()


@respx.mock
async def test_non_json_body_maps_to_schema_changed() -> None:
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(200, text="<html>maintenance</html>"))
    transport = _transport()

    with pytest.raises(ProviderError) as excinfo:
        await transport.request(_provider(), "/v1/search")

    assert excinfo.value.code is ProviderErrorCode.PROVIDER_SCHEMA_CHANGED
    await transport.aclose()


@respx.mock
async def test_circuit_opens_after_repeated_failures() -> None:
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(503))
    transport = _transport()
    provider = _provider()
    guards = transport.guards_for(provider)
    guards.circuit.policy.failure_threshold = 2

    for _ in range(3):
        with pytest.raises(ProviderError):
            await transport.request(provider, "/v1/search")

    assert guards.circuit.state is CircuitState.OPEN

    # Once open, the provider is not called again until the cooldown elapses.
    calls_before = respx.calls.call_count
    with pytest.raises(ProviderError) as excinfo:
        await transport.request(provider, "/v1/search")
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_OUTAGE
    assert respx.calls.call_count == calls_before
    await transport.aclose()


@respx.mock
async def test_auth_failure_does_not_trip_the_circuit() -> None:
    """A 401 says our configuration is wrong, not that the provider is down."""
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(401))
    transport = _transport()
    provider = _provider()
    guards = transport.guards_for(provider)
    guards.circuit.policy.failure_threshold = 2

    for _ in range(3):
        with pytest.raises(ProviderError):
            await transport.request(provider, "/v1/search")

    assert guards.circuit.state is CircuitState.CLOSED
    await transport.aclose()


async def test_absolute_url_off_the_configured_host_is_refused() -> None:
    """SSRF invariant: a provider base URL comes from config, and an adapter
    cannot redirect a call somewhere else."""
    transport = _transport()
    with pytest.raises(ProviderError) as excinfo:
        transport.build_url(_provider(), "https://attacker.example/v1/search")
    assert excinfo.value.code is ProviderErrorCode.PROVIDER_OUTAGE
    await transport.aclose()


async def test_relative_path_resolves_against_the_configured_base() -> None:
    transport = _transport()
    url = transport.build_url(_provider(), "/v1/search")
    assert url == "https://geocoding-api.open-meteo.com/v1/search"
    await transport.aclose()


async def test_non_callable_provider_is_never_requested() -> None:
    transport = _transport()
    entry = next(p for p in load_registry(REGISTRY_PATH).providers if p.id == "openrouteservice")
    blocked = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.PENDING_CREDENTIAL,
        base_url="https://api.openrouteservice.org",
        missing_credentials=["ORS_API_KEY"],
        reason="missing credential: ORS_API_KEY",
    )

    with pytest.raises(ProviderError) as excinfo:
        await transport.request(blocked, "/v2/directions/driving-car/geojson")

    assert excinfo.value.code is ProviderErrorCode.PROVIDER_AUTH
    await transport.aclose()


@respx.mock
async def test_quota_headers_are_recorded_when_present() -> None:
    respx.get(GEOCODE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={"x-ratelimit-remaining": "17", "x-ratelimit-limit": "100"},
        )
    )
    transport = _transport()
    provider = _provider()
    await transport.request(provider, "/v1/search")

    guards = transport.guards_for(provider)
    assert guards.quota.remaining == 17
    assert guards.quota.limit == 100
    assert guards.quota.exhausted is False
    await transport.aclose()


@respx.mock
async def test_quota_stays_unknown_when_the_provider_reports_nothing() -> None:
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    transport = _transport()
    provider = _provider()
    await transport.request(provider, "/v1/search")

    assert transport.guards_for(provider).quota.remaining is None
    await transport.aclose()


@respx.mock
async def test_a_non_json_body_is_fine_when_decoding_is_off() -> None:
    """A health probe asks whether the provider answered, not what shape its
    body is. Reporting PROVIDER_SCHEMA_CHANGED for an empty 204 would name the
    wrong problem."""
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(204))
    transport = _transport()

    response = await transport.request(_provider(), "/v1/search", decode_json=False)

    assert response.status_code == 204
    assert response.payload is None
    await transport.aclose()
