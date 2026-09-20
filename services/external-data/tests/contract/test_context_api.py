"""Contract tests for POST /internal/v1/context/query.

This is the endpoint module 03 calls to find out everything module 04 knows
about a journey, so the shape of a *partial* answer matters as much as a whole
one. Two failure modes are worse than an error here:

A capability missing from the response reads as "nothing to report". For
hazards that is the opposite answer, and nothing downstream can tell the
difference.

A combined answer that carries a risk verdict module 04 never made would hand
module 07 a conclusion dressed as evidence.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import get_settings
from tests.conftest import TEST_TOKEN, load_fixture

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
PATH = "/internal/v1/context/query"

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
POIS_URL = "https://api.openrouteservice.org/pois"

BANGKOK = [100.5383, 13.7649]
AYUTTHAYA = [100.5878, 14.3532]

# No bbox: the captured hazard feeds cover the whole world, and a Thailand box
# would legitimately filter every one of them out - which is correct behaviour
# but makes a poor fixture for "did all four capabilities answer".
FULL_QUERY: dict[str, Any] = {
    "samples": [{"latitude": 13.7649, "longitude": 100.5383, "sample_id": "origin"}],
    "waypoints": [BANGKOK, AYUTTHAYA],
    "place_types": ["HOSPITAL", "POLICE"],
    "deadline_seconds": 20,
}


@pytest.fixture
def keyed_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def _mock_everything() -> None:
    respx.get(FORECAST_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("open_meteo_weather/forecast_bangkok.json")
        )
    )
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("usgs/significant_month.json")
        )
    )
    respx.get(GDACS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdacs/eventlist_eq.json"))
    )
    respx.get(EONET_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("eonet/events.json"))
    )
    respx.post(DIRECTIONS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("openrouteservice/directions_bkk_ayutthaya.json")
        )
    )
    respx.post(POIS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("openrouteservice/pois_emergency_bangkok.json")
        )
    )


def _by_capability(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["capability"]: entry for entry in body["data"]["capabilities"]}


# ------------------------------------------------------------- happy path


@respx.mock
def test_one_call_returns_every_capability(keyed_client: TestClient) -> None:
    _mock_everything()
    response = keyed_client.post(PATH, headers=AUTH, json=FULL_QUERY)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["weather"]
    assert data["disaster_events"]
    assert data["routes"]
    assert data["places"]
    assert data["attribution"]


@respx.mock
def test_every_capability_is_named_with_what_happened(
    keyed_client: TestClient,
) -> None:
    _mock_everything()
    response = keyed_client.post(PATH, headers=AUTH, json=FULL_QUERY)

    capabilities = _by_capability(response.json())
    assert set(capabilities) == {
        "WEATHER",
        "DISASTER",
        "ROUTE",
        "TRANSIT",
        "EMERGENCY_DIRECTORY",
    }
    # TRANSIT is not requested here: this query sends no bbox, and transit
    # coverage is per agency, so asking without one would only ever produce
    # OUTSIDE_COVERAGE.
    answered = {k: v["outcome"] for k, v in capabilities.items() if k != "TRANSIT"}
    assert set(answered.values()) == {"ANSWERED"}
    assert capabilities["TRANSIT"]["outcome"] == "NOT_REQUESTED"


@respx.mock
def test_provider_health_rides_along_with_the_records(
    keyed_client: TestClient,
) -> None:
    """A consumer deciding whether to show a "we could not check" banner needs
    this from the same moment as the data, not from a second call."""
    _mock_everything()
    response = keyed_client.post(PATH, headers=AUTH, json=FULL_QUERY)

    health = response.json()["data"]["provider_health"]
    assert health
    assert {"provider", "capability", "effective_status", "health"} <= set(health[0])


@respx.mock
def test_the_combined_answer_still_decides_nothing(keyed_client: TestClient) -> None:
    """The safety invariant. Routes keep `risk_level: UNKNOWN` and disaster
    events keep `severity: UNKNOWN` even when everything is gathered together -
    combining evidence is not the same as judging it."""
    _mock_everything()
    response = keyed_client.post(PATH, headers=AUTH, json=FULL_QUERY)

    data = response.json()["data"]
    for route in data["routes"]:
        assert route["risk_level"] == "UNKNOWN"
        assert route["exposure"] is None
    for event in data["disaster_events"]:
        assert event["severity"] == "UNKNOWN"


@respx.mock
def test_duplicate_hazards_are_grouped_and_still_all_returned(
    keyed_client: TestClient,
) -> None:
    """Grouped, never merged: module 05 cannot decide which of a pair to believe
    about records it never received."""
    _mock_everything()
    response = keyed_client.post(PATH, headers=AUTH, json=FULL_QUERY)

    data = response.json()["data"]
    grouped_ids = {
        event_id
        for group in data["duplicate_groups"]
        for event_id in group.get("event_ids", [])
    }
    returned_ids = {event["event_id"] for event in data["disaster_events"]}
    assert grouped_ids <= returned_ids


# --------------------------------------------------------- partial answers


@respx.mock
def test_one_failing_source_does_not_lose_the_others(
    keyed_client: TestClient,
) -> None:
    _mock_everything()
    respx.post(DIRECTIONS_URL).mock(return_value=httpx.Response(503, json={}))

    response = keyed_client.post(PATH, headers=AUTH, json=FULL_QUERY)

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["weather"]
    assert _by_capability(body)["ROUTE"]["outcome"] == "FAILED"
    assert body["meta"]["degraded_services"]


@respx.mock
def test_a_capability_with_no_credential_is_named_not_omitted(
    client: TestClient,
) -> None:
    """The default test environment has no routing key - the state the team is
    actually deployed in. The answer must say so rather than leaving the caller
    to infer it from a missing list."""
    _mock_everything()
    response = client.post(PATH, headers=AUTH, json=FULL_QUERY)

    assert response.status_code == 200
    route = _by_capability(response.json())["ROUTE"]
    assert route["outcome"] == "UNAVAILABLE"
    assert route["reason"]


@respx.mock
def test_an_unconfigured_capability_is_not_called_degraded(
    client: TestClient,
) -> None:
    """Nobody configured it, so nothing degraded. Marking it would light up the
    degraded list on every request and stop the field meaning anything."""
    _mock_everything()
    response = client.post(PATH, headers=AUTH, json=FULL_QUERY)

    assert response.json()["meta"]["degraded_services"] == []


# -------------------------------------------------------------- selection


@respx.mock
def test_asking_for_one_capability_does_not_call_the_others(
    keyed_client: TestClient,
) -> None:
    """Routing costs 200 calls a day on the free plan; a weather question must
    not spend one."""
    _mock_everything()
    directions = respx.post(DIRECTIONS_URL)

    response = keyed_client.post(
        PATH,
        headers=AUTH,
        json={
            "samples": [{"latitude": 13.7649, "longitude": 100.5383}],
            "include": ["WEATHER"],
            "deadline_seconds": 20,
        },
    )

    assert response.status_code == 200
    assert directions.call_count == 0
    capabilities = _by_capability(response.json())
    assert capabilities["WEATHER"]["outcome"] == "ANSWERED"
    assert capabilities["ROUTE"]["outcome"] == "NOT_REQUESTED"


@respx.mock
def test_sending_no_waypoints_does_not_ask_for_routes(
    keyed_client: TestClient,
) -> None:
    _mock_everything()
    directions = respx.post(DIRECTIONS_URL)

    keyed_client.post(
        PATH,
        headers=AUTH,
        json={"bbox": [99.0, 12.5, 101.5, 15.5], "deadline_seconds": 20},
    )

    assert directions.call_count == 0


# ------------------------------------------------------------- validation


def test_an_empty_query_is_refused(keyed_client: TestClient) -> None:
    """An empty body would ask every provider about everywhere - expensive
    against a free-tier quota and almost never what was meant."""
    response = keyed_client.post(PATH, headers=AUTH, json={"deadline_seconds": 10})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_capability_module_04_cannot_answer_is_refused(
    keyed_client: TestClient,
) -> None:
    """Accepting FLIGHT would invite a caller to build a screen around an
    answer that never arrives: the shared context forbids serving Amadeus test
    data as a real result, and no production credential exists."""
    response = keyed_client.post(
        PATH,
        headers=AUTH,
        json={"bbox": [99.0, 12.5, 101.5, 15.5], "include": ["FLIGHT"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@respx.mock
def test_transit_outside_every_registered_feed_is_not_a_failure(
    keyed_client: TestClient,
) -> None:
    """A Thai bbox is outside the registered New York feed. That is a coverage
    answer, not a degradation - nothing broke."""
    _mock_everything()
    response = keyed_client.post(
        PATH, headers=AUTH, json={"bbox": [99.0, 12.5, 101.5, 15.5]}
    )

    assert response.status_code == 200
    transit = _by_capability(response.json())["TRANSIT"]
    assert transit["outcome"] in ("NOT_COVERED", "UNAVAILABLE")
    assert "TRANSIT" not in response.json()["meta"]["degraded_services"]


def test_a_swapped_waypoint_is_rejected(keyed_client: TestClient) -> None:
    response = keyed_client.post(
        PATH, headers=AUTH, json={"waypoints": [[13.7649, 100.5383], AYUTTHAYA]}
    )
    assert response.status_code == 422


def test_an_unknown_field_is_refused(keyed_client: TestClient) -> None:
    response = keyed_client.post(
        PATH, headers=AUTH, json={"bbox": [99.0, 12.5, 101.5, 15.5], "limit": 5}
    )
    assert response.status_code == 422


def test_context_requires_internal_auth(client: TestClient) -> None:
    response = client.post(PATH, json=FULL_QUERY)
    assert response.status_code == 401
