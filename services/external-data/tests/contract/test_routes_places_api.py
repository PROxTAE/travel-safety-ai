"""Contract tests for POST /internal/v1/routes/query and /places/nearby.

Two properties these exist to protect.

A route must never arrive downstream carrying a risk verdict module 04 did not
make. `exposure` null and `risk_level` UNKNOWN is the whole point: a route over
a closed bridge with `exposure.score = 0` would tell module 07, in the
contract's own vocabulary, that nothing is wrong.

An empty `places` list must mean "nothing is tagged here", never "we could not
reach the directory" - and must never be rendered as "no help nearby".
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import get_settings
from tests.conftest import TEST_TOKEN, load_fixture

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
ROUTES = "/internal/v1/routes/query"
PLACES = "/internal/v1/places/nearby"
DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
POIS_URL = "https://api.openrouteservice.org/pois"

BANGKOK = [100.5383, 13.7649]
AYUTTHAYA = [100.5878, 14.3532]


@pytest.fixture
def keyed_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client whose routing credential is configured.

    The default test environment deliberately has no key, because that is the
    state the team is deployed in; these tests opt in.
    """
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


# ------------------------------------------------------ no credential at all


def test_routes_without_a_credential_are_unsupported_not_a_crash(
    client: TestClient,
) -> None:
    """An unconfigured provider must reach the caller as an honest unavailable
    state, naming what is missing - not as a 500."""
    response = client.post(ROUTES, headers=AUTH, json={"waypoints": [BANGKOK, AYUTTHAYA]})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_COVERAGE"
    assert body["error"]["retryable"] is False


def test_places_without_a_credential_are_unsupported_not_an_empty_list(
    client: TestClient,
) -> None:
    """The dangerous failure mode: returning `[]` here reads as "no hospital
    nearby" when the truth is "we never asked"."""
    response = client.post(PLACES, headers=AUTH, json={"longitude": 100.5383, "latitude": 13.7649})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_COVERAGE"


def test_routes_require_internal_auth(client: TestClient) -> None:
    response = client.post(ROUTES, json={"waypoints": [BANGKOK, AYUTTHAYA]})
    assert response.status_code == 401


# ------------------------------------------------------------------- routing


@respx.mock
def test_routes_are_returned_with_geometry_and_instructions(
    keyed_client: TestClient,
) -> None:
    respx.post(DIRECTIONS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("openrouteservice/directions_bkk_ayutthaya.json")
        )
    )
    response = keyed_client.post(
        ROUTES,
        headers=AUTH,
        json={"waypoints": [BANGKOK, AYUTTHAYA], "mode": "CAR", "alternatives": 2},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["routes"]) == 2
    route = data["routes"][0]
    assert route["geometry"]["type"] == "LineString"
    assert route["distance_m"] > 0
    assert route["segments"][0]["steps"]
    assert data["attribution"]


@respx.mock
def test_no_route_carries_a_risk_verdict(keyed_client: TestClient) -> None:
    """The safety invariant for this endpoint."""
    respx.post(DIRECTIONS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("openrouteservice/directions_bkk_ayutthaya.json")
        )
    )
    response = keyed_client.post(
        ROUTES, headers=AUTH, json={"waypoints": [BANGKOK, AYUTTHAYA], "alternatives": 2}
    )
    for route in response.json()["data"]["routes"]:
        assert route["risk_level"] == "UNKNOWN"
        assert route["exposure"] is None
        assert "INCOMPLETE" in route["quality"]["flags"]


@respx.mock
def test_every_route_carries_provenance_and_quality(keyed_client: TestClient) -> None:
    respx.post(DIRECTIONS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("openrouteservice/directions_bkk_ayutthaya.json")
        )
    )
    response = keyed_client.post(ROUTES, headers=AUTH, json={"waypoints": [BANGKOK, AYUTTHAYA]})
    for route in response.json()["data"]["routes"]:
        # Plural on a route: it has to survive module 05 stitching legs from
        # several providers into one itinerary.
        assert len(route["sources"]) == 1
        assert route["sources"][0]["provider"] == "openrouteservice"
        assert route["sources"][0]["license"]
        assert route["quality"]["status"]


@respx.mock
def test_a_coordinate_off_the_road_network_is_coverage_not_an_outage(
    keyed_client: TestClient,
) -> None:
    respx.post(DIRECTIONS_URL).mock(
        return_value=httpx.Response(
            404, json=load_fixture("openrouteservice/directions_no_route.json")
        )
    )
    response = keyed_client.post(ROUTES, headers=AUTH, json={"waypoints": [BANGKOK, AYUTTHAYA]})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_COVERAGE"
    assert body["error"]["retryable"] is False


def test_a_swapped_coordinate_is_rejected_at_the_boundary(
    keyed_client: TestClient,
) -> None:
    """Latitude 100 does not exist; it is lon/lat written the wrong way round."""
    response = keyed_client.post(
        ROUTES, headers=AUTH, json={"waypoints": [[13.7649, 100.5383], AYUTTHAYA]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_too_many_alternatives_is_a_field_error(keyed_client: TestClient) -> None:
    response = keyed_client.post(
        ROUTES, headers=AUTH, json={"waypoints": [BANGKOK, AYUTTHAYA], "alternatives": 9}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert any(error["path"].endswith("alternatives") for error in body["error"]["field_errors"])


def test_a_mode_the_provider_cannot_route_is_unsupported(
    keyed_client: TestClient,
) -> None:
    response = keyed_client.post(
        ROUTES, headers=AUTH, json={"waypoints": [BANGKOK, AYUTTHAYA], "mode": "TRAIN"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNSUPPORTED_COVERAGE"


def test_an_unknown_field_is_refused(keyed_client: TestClient) -> None:
    response = keyed_client.post(
        ROUTES, headers=AUTH, json={"waypoints": [BANGKOK, AYUTTHAYA], "limit": 3}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------- emergency places


@respx.mock
def test_places_come_back_with_the_directory_caveat(keyed_client: TestClient) -> None:
    """Said in the payload, not only in a doc comment: whoever renders this may
    never read the doc."""
    respx.post(POIS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("openrouteservice/pois_emergency_bangkok.json")
        )
    )
    response = keyed_client.post(
        PLACES,
        headers=AUTH,
        json={
            "longitude": 100.5383,
            "latitude": 13.7649,
            "radius_m": 2000,
            "place_types": ["HOSPITAL", "POLICE"],
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["places"]
    assert "not an official" in data["directory_caveat"]
    assert data["attribution"]


@respx.mock
def test_nothing_tagged_nearby_is_an_empty_list_and_still_a_success(
    keyed_client: TestClient,
) -> None:
    payload = load_fixture("openrouteservice/pois_emergency_bangkok.json")
    payload["features"] = []
    respx.post(POIS_URL).mock(return_value=httpx.Response(200, json=payload))
    response = keyed_client.post(PLACES, headers=AUTH, json={"longitude": 0.0, "latitude": 0.0})
    assert response.status_code == 200
    assert response.json()["data"]["places"] == []


@respx.mock
def test_every_place_carries_quality_flags(keyed_client: TestClient) -> None:
    respx.post(POIS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("openrouteservice/pois_emergency_bangkok.json")
        )
    )
    response = keyed_client.post(
        PLACES, headers=AUTH, json={"longitude": 100.5383, "latitude": 13.7649}
    )
    for place in response.json()["data"]["places"]:
        assert place["quality"]["status"] == "PARTIAL"
        assert place["source"]["provider"] == "ors_pois"


def test_an_unknown_place_type_is_a_field_error(keyed_client: TestClient) -> None:
    response = keyed_client.post(
        PLACES,
        headers=AUTH,
        json={"longitude": 100.5383, "latitude": 13.7649, "place_types": ["CASINO"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_radius_past_the_provider_limit_is_refused(keyed_client: TestClient) -> None:
    response = keyed_client.post(
        PLACES,
        headers=AUTH,
        json={"longitude": 100.5383, "latitude": 13.7649, "radius_m": 500_000},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@respx.mock
def test_an_exact_coordinate_is_not_echoed_into_the_response(
    keyed_client: TestClient,
) -> None:
    """Security invariant § 11. The caller's own position is the one coordinate
    in this exchange that identifies a person."""
    respx.post(POIS_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("openrouteservice/pois_emergency_bangkok.json")
        )
    )
    response = keyed_client.post(
        PLACES, headers=AUTH, json={"longitude": 100.538312, "latitude": 13.764987}
    )
    assert "100.538312" not in response.text
    assert "13.764987" not in response.text
