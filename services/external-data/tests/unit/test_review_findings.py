"""Regression probes for the four findings in the PR #7 review.

Findings A and B are the dangerous pair: each one hands a caller a
plausible-looking forecast for the wrong place or the wrong hour, with no error
raised anywhere. The first two tests here came from the reviewer and failed
against the original code; they are kept as written apart from the `normalize`
signature change that fixes A.
"""

from __future__ import annotations

import copy
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.adapters.open_meteo_weather import (
    CoordinateSample,
    OpenMeteoWeatherAdapter,
    WeatherQuery,
)
from app.domain.enums import ProviderStatus
from app.observability.logging import _redact_text
from app.providers.registry import Defaults, ResolvedProvider, load_registry
from app.settings import get_settings
from app.transport.http import ProviderResponse, ProviderTransport
from tests.conftest import REGISTRY_PATH, load_fixture

SINGLE = "open_meteo_weather/forecast_bangkok.json"
BATCHED = "open_meteo_weather/forecast_batched.json"


def _adapter(cache: Any = None) -> OpenMeteoWeatherAdapter:
    entry = next(
        p for p in load_registry(REGISTRY_PATH).providers if p.id == "open_meteo_forecast"
    )
    provider = ResolvedProvider(
        entry=entry,
        effective_status=ProviderStatus.ACTIVE,
        base_url=get_settings().base_url_for(entry.base_url_env),
    )
    return OpenMeteoWeatherAdapter(
        provider, ProviderTransport(Defaults()), cache, env="test"
    )


def _response(payload: Any) -> ProviderResponse:
    return ProviderResponse(
        payload=payload,
        status_code=200,
        headers={},
        url="https://api.open-meteo.com/v1/forecast",
        fetched_at=time.time(),
        elapsed_seconds=0.2,
    )


async def _noop(*args: Any, **kwargs: Any) -> None:
    return None


class _FakeCache:
    """Minimal stand-in for ProviderCache: a dict, no locks."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, key: str, provider_id: str) -> Any:
        payload = self.store.get(key)
        if payload is None:
            return None
        from app.cache.provider_cache import CacheHit

        return CacheHit(payload=payload, negative=False)

    async def acquire_lock(self, key: str, provider_id: str) -> bool:
        return True

    async def release_lock(self, key: str) -> None:
        return None

    async def set(self, key: str, provider_id: str, payload: Any, ttl: int) -> None:
        self.store[key] = payload

    async def set_negative(self, key: str, provider_id: str, ttl: int) -> None:
        return None


# ----------------------------------------------------------------- finding A


async def test_concurrent_queries_do_not_swap_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One adapter instance serves every request, and there is an `await` between
    building the request and normalising the response. The original code stashed
    the query on `self`, so a second request arriving mid-flight relabelled the
    first request's forecast with its own samples."""
    import asyncio

    adapter = _adapter()
    bangkok_payload = load_fixture(SINGLE)
    chiang_mai_payload = load_fixture(BATCHED)[1]

    async def fake_fetch(
        request: Any, *, deadline_seconds: float | None = None
    ) -> ProviderResponse:
        # Request A (Bangkok) yields; request B (Chiang Mai) overtakes it.
        is_bangkok = request.params["latitude"].startswith("13.")
        await asyncio.sleep(0.05 if is_bangkok else 0.0)
        return _response(bangkok_payload if is_bangkok else chiang_mai_payload)

    monkeypatch.setattr(adapter, "fetch", fake_fetch)
    monkeypatch.setattr(adapter, "_record_observation", _noop)

    query_a = WeatherQuery(
        samples=[CoordinateSample(13.7563, 100.5018, sample_id="A-bkk")]
    )
    query_b = WeatherQuery(
        samples=[CoordinateSample(18.7883, 98.9853, sample_id="B-cnx")]
    )

    result_a, result_b = await asyncio.gather(
        adapter.query(query_a), adapter.query(query_b)
    )

    assert {p.sample_id for p in result_a} == {"A-bkk"}, {p.sample_id for p in result_a}
    assert {p.sample_id for p in result_b} == {"B-cnx"}


async def test_concurrent_queries_keep_their_own_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The label is only half of it: the forecast values must belong to the
    place that was asked about."""
    import asyncio

    adapter = _adapter()
    bangkok_payload = load_fixture(SINGLE)
    chiang_mai_payload = load_fixture(BATCHED)[1]

    async def fake_fetch(
        request: Any, *, deadline_seconds: float | None = None
    ) -> ProviderResponse:
        is_bangkok = request.params["latitude"].startswith("13.")
        await asyncio.sleep(0.05 if is_bangkok else 0.0)
        return _response(bangkok_payload if is_bangkok else chiang_mai_payload)

    monkeypatch.setattr(adapter, "fetch", fake_fetch)
    monkeypatch.setattr(adapter, "_record_observation", _noop)

    result_a, result_b = await asyncio.gather(
        adapter.query(
            WeatherQuery(samples=[CoordinateSample(13.7563, 100.5018, sample_id="a")])
        ),
        adapter.query(
            WeatherQuery(samples=[CoordinateSample(18.7883, 98.9853, sample_id="b")])
        ),
    )

    # Bangkok is south of Chiang Mai; a swap inverts this.
    assert result_a[0].location.latitude < result_b[0].location.latitude


# ----------------------------------------------------------------- finding B


async def test_cache_hit_respects_a_different_eta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What gets cached is the normalised records, which ETA selection has
    already narrowed to one hour and labelled with the first caller's ids. The
    cache key has to cover both, or the second traveller gets the first one's
    hour back under their own name."""
    cache = _FakeCache()
    adapter = _adapter(cache)
    single = load_fixture(SINGLE)
    calls = 0

    async def fake_fetch(
        request: Any, *, deadline_seconds: float | None = None
    ) -> ProviderResponse:
        nonlocal calls
        calls += 1
        return _response(copy.deepcopy(single))

    monkeypatch.setattr(adapter, "fetch", fake_fetch)
    monkeypatch.setattr(adapter, "_record_observation", _noop)

    first_hour = datetime.fromisoformat(single["hourly"]["time"][2]).replace(tzinfo=UTC)
    later_hour = datetime.fromisoformat(single["hourly"]["time"][20]).replace(tzinfo=UTC)

    first = await adapter.query(
        WeatherQuery(
            samples=[
                CoordinateSample(13.7563, 100.5018, eta=first_hour, sample_id="first")
            ]
        )
    )
    second = await adapter.query(
        WeatherQuery(
            samples=[
                CoordinateSample(13.7563, 100.5018, eta=later_hour, sample_id="second")
            ]
        )
    )

    assert first[0].valid_at == first_hour
    assert second[0].valid_at == later_hour, (second[0].valid_at, calls)
    assert second[0].sample_id == "second"


async def test_identical_queries_still_share_a_cache_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key gained fields, so check it did not stop caching altogether."""
    cache = _FakeCache()
    adapter = _adapter(cache)
    single = load_fixture(SINGLE)
    calls = 0

    async def fake_fetch(
        request: Any, *, deadline_seconds: float | None = None
    ) -> ProviderResponse:
        nonlocal calls
        calls += 1
        return _response(copy.deepcopy(single))

    monkeypatch.setattr(adapter, "fetch", fake_fetch)
    monkeypatch.setattr(adapter, "_record_observation", _noop)

    eta = datetime.fromisoformat(single["hourly"]["time"][4]).replace(tzinfo=UTC)
    query = WeatherQuery(
        samples=[CoordinateSample(13.7563, 100.5018, eta=eta, sample_id="same")]
    )

    await adapter.query(query)
    await adapter.query(query)

    assert calls == 1


# ----------------------------------------------------------------- finding D


def test_uuid_survives_redaction() -> None:
    """request_id and correlation_id are uuid4s. The phone pattern was eating
    roughly one in four of them, which breaks tracing precisely when it is
    needed."""
    mangled = [
        str(value)
        for value in (uuid.uuid4() for _ in range(2000))
        if _redact_text(str(value)) != str(value)
    ]
    assert mangled == [], f"{len(mangled)}/2000 uuids mangled, e.g. {mangled[:2]}"


def test_uuid_inside_a_log_line_survives() -> None:
    request_id = str(uuid.uuid4())
    line = f"request_id={request_id} finished in 12 ms"
    assert request_id in _redact_text(line)


def test_phone_numbers_are_still_redacted_alongside_uuids() -> None:
    """The fix must not turn redaction off for the thing it is actually for."""
    text = f"user {uuid.uuid4()} called +66 81 234 5678"
    redacted = _redact_text(text)
    assert "[PHONE]" in redacted
    assert not re.search(r"\+66 81 234 5678", redacted)
