"""Contract tests for POST /internal/v1/disasters/query.

The property this file exists to protect: an empty `events` list must mean "no
hazards were reported", and must never be what a caller sees when the hazard
sources could not be reached.

Two sources are configured (USGS and GDACS), so these also pin how a partial
answer is reported — and the difference between a source that failed and a
source that simply does not publish the hazard being asked about.
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
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def _mock_both(usgs: Any = None, gdacs: Any = None) -> None:
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(
            200, json=usgs if usgs is not None else load_fixture("usgs/significant_month.json")
        )
    )
    respx.get(GDACS_URL).mock(
        return_value=httpx.Response(
            200, json=gdacs if gdacs is not None else load_fixture("gdacs/eventlist_eq.json")
        )
    )


class _FailingAdapter:
    """Stands in for a third disaster source that is down."""

    provider_id = "nasa_eonet"

    async def query(self, query: Any, **kwargs: Any) -> list[Any]:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_OUTAGE, self.provider_id, message="down"
        )


@respx.mock
def test_returns_canonical_events_from_every_source(client: TestClient) -> None:
    _mock_both()
    response = client.post(PATH, json={}, headers=AUTH)
    assert response.status_code == 200

    body = response.json()
    assert set(body["data"]["sources"]) == {"usgs_earthquake", "gdacs"}
    assert body["meta"]["degraded_services"] == []

    providers = {event["source"]["provider"] for event in body["data"]["events"]}
    assert providers == {"usgs_earthquake", "gdacs"}


@respx.mock
def test_duplicates_across_sources_are_kept_not_merged(client: TestClient) -> None:
    """The same quake appears in more than one feed. The plan forbids dropping
    one here — module 05 resolves them, and it cannot resolve what it never
    receives."""
    _mock_both()
    body = client.post(PATH, json={}, headers=AUTH).json()

    usgs = [e for e in body["data"]["events"] if e["source"]["provider"] == "usgs_earthquake"]
    gdacs = [e for e in body["data"]["events"] if e["source"]["provider"] == "gdacs"]

    assert usgs and gdacs
    assert len(body["data"]["events"]) == len(usgs) + len(gdacs)
    # Every record keeps the identifiers that make matching possible.
    assert any(event["cross_reference_ids"] for event in usgs)
    assert any(event["cross_reference_ids"] for event in gdacs)


@respx.mock
def test_events_are_newest_first_across_sources(client: TestClient) -> None:
    _mock_both()
    events = client.post(PATH, json={}, headers=AUTH).json()["data"]["events"]
    times = [event["effective_at"] for event in events]
    assert times == sorted(times, reverse=True)


@respx.mock
def test_attribution_covers_every_answering_source(client: TestClient) -> None:
    _mock_both()
    attribution = client.post(PATH, json={}, headers=AUTH).json()["data"]["attribution"]

    assert any("U.S. Geological Survey" in text for text in attribution)
    assert any("GDACS" in text for text in attribution)


@respx.mock
def test_an_empty_feed_is_a_success_with_no_events(client: TestClient) -> None:
    """No hazards reported is a real answer."""
    empty = {"type": "FeatureCollection", "features": []}
    _mock_both(usgs=empty, gdacs=empty)

    response = client.post(PATH, json={}, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["events"] == []
    assert set(body["data"]["sources"]) == {"usgs_earthquake", "gdacs"}
    assert body["meta"]["degraded_services"] == []


@respx.mock
def test_every_source_failing_is_an_error_not_an_empty_list(
    client: TestClient,
) -> None:
    """The one answer this module must never invent. An empty list here would
    read as "no hazards on your route"."""
    respx.get(USGS_URL).mock(return_value=httpx.Response(503))
    respx.get(GDACS_URL).mock(return_value=httpx.Response(503))

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
    _mock_both()
    registry = client.app.state.adapters  # type: ignore[attr-defined]
    registry._adapters["nasa_eonet"] = _FailingAdapter()

    try:
        body = client.post(PATH, json={}, headers=AUTH).json()
    finally:
        registry._adapters.pop("nasa_eonet", None)

    assert body["data"]["events"]
    assert set(body["data"]["sources"]) == {"usgs_earthquake", "gdacs"}
    assert body["meta"]["degraded_services"] == ["nasa_eonet"]


@respx.mock
def test_a_source_that_does_not_cover_the_hazard_is_not_degraded(
    client: TestClient,
) -> None:
    """USGS publishes earthquakes only. On a flood query it has nothing to say,
    which is different from being broken — marking it degraded would set that
    field on every flood query and drain it of meaning."""
    _mock_both()

    body = client.post(PATH, json={"event_types": ["FLOOD"]}, headers=AUTH).json()

    assert body["data"]["sources"] == ["gdacs"]
    assert body["data"]["sources_not_covering_query"] == ["usgs_earthquake"]
    assert body["meta"]["degraded_services"] == []


@respx.mock
def test_a_hazard_no_source_covers_is_unsupported_coverage(
    client: TestClient,
) -> None:
    _mock_both()
    response = client.post(
        PATH, json={"event_types": ["TRANSPORT_CLOSURE"]}, headers=AUTH
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_COVERAGE"
    assert "data" not in response.json()


@respx.mock
def test_bbox_narrows_the_result(client: TestClient) -> None:
    raw = load_fixture("usgs/significant_month.json")
    _mock_both(usgs=raw)

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
        json={"start": now.isoformat(), "end": (now - timedelta(hours=1)).isoformat()},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_rejects_an_unknown_field(client: TestClient) -> None:
    assert client.post(PATH, json={"radius_km": 10}, headers=AUTH).status_code == 422


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
