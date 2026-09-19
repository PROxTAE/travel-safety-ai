"""Contract tests for POST /internal/v1/disasters/query.

The property this file exists to protect: an empty `events` list must mean "no
hazards were reported", and must never be what a caller sees when the hazard
sources could not be reached.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.domain.errors import ProviderError, ProviderErrorCode
from app.main import create_app
from tests.conftest import TEST_TOKEN, load_fixture

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
PATH = "/internal/v1/disasters/query"
USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


class _FailingAdapter:
    """Stands in for a second disaster source that is down."""

    provider_id = "gdacs"

    async def query(self, query: Any, **kwargs: Any) -> list[Any]:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_OUTAGE, self.provider_id, message="down"
        )


@respx.mock
def test_returns_canonical_events(client: TestClient) -> None:
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("usgs/significant_month.json"))
    )

    response = client.post(PATH, json={}, headers=AUTH)
    assert response.status_code == 200

    body = response.json()
    event = body["data"]["events"][0]
    assert event["event_type"] == "EARTHQUAKE"
    assert event["geometry"]["type"] == "Point"
    assert len(event["geometry"]["coordinates"]) == 2
    assert event["official"] is True
    assert event["source"]["observed_at"] is not None  # a real observation time
    assert event["severity"] == "UNKNOWN"  # pending Q2/Q3
    assert body["data"]["sources"] == ["usgs_earthquake"]


@respx.mock
def test_events_are_newest_first(client: TestClient) -> None:
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("usgs/significant_month.json"))
    )
    events = client.post(PATH, json={}, headers=AUTH).json()["data"]["events"]
    times = [event["effective_at"] for event in events]
    assert times == sorted(times, reverse=True)


@respx.mock
def test_response_carries_attribution(client: TestClient) -> None:
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("usgs/significant_month.json"))
    )
    body = client.post(PATH, json={}, headers=AUTH).json()
    assert any("U.S. Geological Survey" in text for text in body["data"]["attribution"])


@respx.mock
def test_an_empty_feed_is_a_success_with_no_events(client: TestClient) -> None:
    """No earthquakes reported is a real answer."""
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(200, json={"type": "FeatureCollection", "features": []})
    )
    response = client.post(PATH, json={}, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["events"] == []
    assert body["data"]["sources"] == ["usgs_earthquake"]
    assert body["meta"]["degraded_services"] == []


@respx.mock
def test_every_source_failing_is_an_error_not_an_empty_list(
    client: TestClient,
) -> None:
    """The one answer this module must never invent. An empty list here would
    read as "no hazards on your route"."""
    respx.get(USGS_URL).mock(return_value=httpx.Response(503))

    response = client.post(PATH, json={}, headers=AUTH)

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "data" not in body


@respx.mock
def test_one_source_failing_still_answers_but_reports_degraded(
    client: TestClient,
) -> None:
    """A partial answer is useful; a silent partial answer is not."""
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("usgs/significant_month.json"))
    )
    registry = client.app.state.adapters  # type: ignore[attr-defined]
    registry._adapters["gdacs"] = _FailingAdapter()

    try:
        body = client.post(PATH, json={}, headers=AUTH).json()
    finally:
        registry._adapters.pop("gdacs", None)

    assert body["data"]["events"]
    assert body["data"]["sources"] == ["usgs_earthquake"]
    assert body["meta"]["degraded_services"] == ["gdacs"]


@respx.mock
def test_bbox_narrows_the_result(client: TestClient) -> None:
    raw = load_fixture("usgs/significant_month.json")
    respx.get(USGS_URL).mock(return_value=httpx.Response(200, json=raw))

    everything = client.post(PATH, json={}, headers=AUTH).json()["data"]["events"]
    first = raw["features"][0]["geometry"]["coordinates"]
    narrowed = client.post(
        PATH,
        json={"bbox": [first[0] - 0.5, first[1] - 0.5, first[0] + 0.5, first[1] + 0.5]},
        headers=AUTH,
    ).json()["data"]["events"]

    assert len(narrowed) < len(everything)


def test_requires_authentication(client: TestClient) -> None:
    assert client.post(PATH, json={}).status_code == 401


def test_rejects_an_inverted_bbox(client: TestClient) -> None:
    response = client.post(PATH, json={"bbox": [0, 10, 1, 5]}, headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_rejects_an_out_of_range_bbox(client: TestClient) -> None:
    assert (
        client.post(PATH, json={"bbox": [0, 0, 200, 10]}, headers=AUTH).status_code == 422
    )


def test_rejects_a_naive_timestamp(client: TestClient) -> None:
    response = client.post(PATH, json={"start": "2026-09-19T08:00:00"}, headers=AUTH)
    assert response.status_code == 422


def test_rejects_a_reversed_window(client: TestClient) -> None:
    now = datetime.now(UTC)
    response = client.post(
        PATH,
        json={
            "start": now.isoformat(),
            "end": (now - timedelta(hours=1)).isoformat(),
        },
        headers=AUTH,
    )
    assert response.status_code == 422


def test_rejects_an_unknown_field(client: TestClient) -> None:
    assert client.post(PATH, json={"radius_km": 10}, headers=AUTH).status_code == 422


@respx.mock
def test_requesting_only_unsupported_hazards_is_unsupported_coverage(
    client: TestClient,
) -> None:
    """USGS publishes earthquakes only. Asking it for floods is out of
    coverage, not an empty result."""
    response = client.post(PATH, json={"event_types": ["FLOOD"]}, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_COVERAGE"


def test_rejects_an_unknown_event_type(client: TestClient) -> None:
    response = client.post(PATH, json={"event_types": ["METEOR"]}, headers=AUTH)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field_errors"]


class _SlowAdapter:
    """A source that takes a known time to answer."""

    def __init__(self, provider_id: str, seconds: float) -> None:
        self.provider_id = provider_id
        self.seconds = seconds

    async def query(self, query: Any, **kwargs: Any) -> list[Any]:
        import asyncio

        await asyncio.sleep(self.seconds)
        return []


def test_sources_are_queried_in_parallel(client: TestClient) -> None:
    """Shared context § 7 item 4: real providers are fetched in parallel.

    Sequentially this endpoint cost the sum of every source's latency - 12s for
    a global query measured in review - and the sum of every source's *timeout*
    when one hung. Module 03 budgets per tool call, so that difference is the
    whole endpoint's usability.
    """
    import time

    delay = 0.4
    registry = client.app.state.adapters  # type: ignore[attr-defined]
    saved = dict(registry._adapters)
    # Keyed by real registry ids: all_for_kind resolves through the registry,
    # so an invented id would simply not be found.
    registry._adapters = {
        provider_id: _SlowAdapter(provider_id, delay)
        for provider_id in ("usgs_earthquake", "gdacs", "nasa_eonet")
    }

    try:
        started = time.perf_counter()
        response = client.post(PATH, json={}, headers=AUTH)
        elapsed = time.perf_counter() - started
    finally:
        registry._adapters = saved

    assert response.status_code == 200
    # Three sources at 0.4s each: ~0.4s in parallel, ~1.2s sequentially.
    assert elapsed < delay * 2, f"took {elapsed:.2f}s for 3 x {delay}s sources"


def test_a_slow_source_does_not_delay_the_others(client: TestClient) -> None:
    """The case that hurt most: one source burning its full deadline used to
    push every source behind it out by that much."""
    import time

    registry = client.app.state.adapters  # type: ignore[attr-defined]
    saved = dict(registry._adapters)
    registry._adapters = {
        "usgs_earthquake": _SlowAdapter("usgs_earthquake", 0.05),
        "gdacs": _SlowAdapter("gdacs", 0.6),
    }

    try:
        started = time.perf_counter()
        body = client.post(PATH, json={}, headers=AUTH).json()
        elapsed = time.perf_counter() - started
    finally:
        registry._adapters = saved

    assert set(body["data"]["sources"]) == {"usgs_earthquake", "gdacs"}
    assert elapsed < 0.6 + 0.3  # the slowest source, not the sum
