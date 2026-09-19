"""Contract tests for the Phase 2 endpoints.

The provider is mocked at the HTTP boundary with a captured real payload, so the
whole stack runs: auth, validation, adapter, transport, envelope. Redis and
Postgres are absent, which also proves the cache degrades instead of taking the
capability down.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import TEST_TOKEN, load_fixture

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
GEOCODE_PATH = "/internal/v1/geocode/search"
WEATHER_PATH = "/internal/v1/weather/query"

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


# ------------------------------------------------------------------- geocoding


@respx.mock
def test_geocode_returns_canonical_locations(client: TestClient) -> None:
    respx.get(GEOCODE_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("open_meteo_geocoding/search_bangkok.json")
        )
    )

    response = client.post(GEOCODE_PATH, json={"query": "Bangkok"}, headers=AUTH)
    assert response.status_code == 200

    body = response.json()
    first = body["data"]["results"][0]["location"]
    assert first["coordinates"]["type"] == "Point"
    assert first["provider"] == "open_meteo_geocoding"
    assert first["confirmed_by_user"] is False
    assert body["meta"]["contract_version"] == "1.0.0"


@respx.mock
def test_geocode_response_carries_attribution(client: TestClient) -> None:
    """Open-Meteo's licence requires it, so the UI has to be given the string."""
    respx.get(GEOCODE_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("open_meteo_geocoding/search_bangkok.json")
        )
    )
    body = client.post(GEOCODE_PATH, json={"query": "Bangkok"}, headers=AUTH).json()
    assert any("Open-Meteo" in text for text in body["data"]["attribution"])


@respx.mock
def test_geocode_no_match_is_an_empty_success_not_an_error(
    client: TestClient,
) -> None:
    respx.get(GEOCODE_URL).mock(
        return_value=httpx.Response(200, json={"generationtime_ms": 0.1})
    )
    response = client.post(
        GEOCODE_PATH, json={"query": "zzzzzzzzzz"}, headers=AUTH
    )
    assert response.status_code == 200
    assert response.json()["data"]["results"] == []


def test_geocode_requires_authentication(client: TestClient) -> None:
    response = client.post(GEOCODE_PATH, json={"query": "Bangkok"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_geocode_rejects_an_empty_query(client: TestClient) -> None:
    response = client.post(GEOCODE_PATH, json={"query": ""}, headers=AUTH)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field_errors"]


def test_geocode_rejects_an_unknown_field(client: TestClient) -> None:
    """Silently dropping an unexpected field leaves the caller wondering why
    their filter did nothing."""
    response = client.post(
        GEOCODE_PATH, json={"query": "Bangkok", "radius": 10}, headers=AUTH
    )
    assert response.status_code == 422


@respx.mock
def test_provider_rate_limit_surfaces_as_429(client: TestClient) -> None:
    respx.get(GEOCODE_URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    response = client.post(GEOCODE_PATH, json={"query": "Bangkok"}, headers=AUTH)

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["retryable"] is True


@respx.mock
def test_provider_outage_never_names_the_provider(client: TestClient) -> None:
    respx.get(GEOCODE_URL).mock(return_value=httpx.Response(503))
    body = client.post(GEOCODE_PATH, json={"query": "Bangkok"}, headers=AUTH).json()

    assert body["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "open_meteo" not in response_text(body)
    assert "503" not in response_text(body)


@respx.mock
def test_malformed_provider_body_is_not_served_as_data(client: TestClient) -> None:
    respx.get(GEOCODE_URL).mock(
        return_value=httpx.Response(200, text="<html>maintenance</html>")
    )
    response = client.post(GEOCODE_PATH, json={"query": "Bangkok"}, headers=AUTH)
    assert response.status_code == 503
    assert "data" not in response.json()


# --------------------------------------------------------------------- weather


@respx.mock
def test_weather_returns_forecast_points(client: TestClient) -> None:
    respx.get(FORECAST_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("open_meteo_weather/forecast_bangkok.json")
        )
    )

    response = client.post(
        WEATHER_PATH,
        json={"samples": [{"latitude": 13.7563, "longitude": 100.5018}]},
        headers=AUTH,
    )
    assert response.status_code == 200

    forecasts = response.json()["data"]["forecasts"]
    assert forecasts
    point = forecasts[0]
    assert point["valid_at"].endswith("Z") or "+00:00" in point["valid_at"]
    assert point["source"]["observed_at"] is None
    assert point["severity"] == "UNKNOWN"
    assert point["quality"]["score"] is None


@respx.mock
def test_weather_eta_returns_one_point_per_sample(client: TestClient) -> None:
    raw = load_fixture("open_meteo_weather/forecast_bangkok.json")
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=raw))

    eta = datetime.fromisoformat(raw["hourly"]["time"][3]).replace(tzinfo=UTC)
    response = client.post(
        WEATHER_PATH,
        json={
            "samples": [
                {
                    "latitude": 13.7563,
                    "longitude": 100.5018,
                    "eta": eta.isoformat(),
                    "sample_id": "p0",
                }
            ]
        },
        headers=AUTH,
    )

    forecasts = response.json()["data"]["forecasts"]
    assert len(forecasts) == 1
    assert forecasts[0]["sample_id"] == "p0"


@respx.mock
def test_weather_reports_how_many_samples_were_requested(
    client: TestClient,
) -> None:
    respx.get(FORECAST_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("open_meteo_weather/forecast_batched.json")
        )
    )
    body = client.post(
        WEATHER_PATH,
        json={
            "samples": [
                {"latitude": 13.7563, "longitude": 100.5018},
                {"latitude": 18.7883, "longitude": 98.9853},
            ]
        },
        headers=AUTH,
    ).json()

    assert body["data"]["requested_samples"] == 2


def test_weather_rejects_a_naive_eta(client: TestClient) -> None:
    """A timestamp without an offset is ambiguous, and guessing the zone is how
    a forecast ends up seven hours out."""
    response = client.post(
        WEATHER_PATH,
        json={
            "samples": [
                {"latitude": 13.7, "longitude": 100.5, "eta": "2026-09-19T08:00:00"}
            ]
        },
        headers=AUTH,
    )
    assert response.status_code == 422


def test_weather_rejects_an_impossible_coordinate(client: TestClient) -> None:
    response = client.post(
        WEATHER_PATH,
        json={"samples": [{"latitude": 100.0, "longitude": 100.5}]},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_weather_rejects_a_reversed_window(client: TestClient) -> None:
    now = datetime.now(UTC)
    response = client.post(
        WEATHER_PATH,
        json={
            "samples": [{"latitude": 13.7, "longitude": 100.5}],
            "start": now.isoformat(),
            "end": (now - timedelta(hours=2)).isoformat(),
        },
        headers=AUTH,
    )
    assert response.status_code == 422


def test_weather_rejects_an_empty_sample_list(client: TestClient) -> None:
    response = client.post(WEATHER_PATH, json={"samples": []}, headers=AUTH)
    assert response.status_code == 422


@respx.mock
def test_capability_works_without_redis(client: TestClient) -> None:
    """No Redis is running in this suite. The cache must degrade to a miss
    rather than take the capability down with it."""
    respx.get(GEOCODE_URL).mock(
        return_value=httpx.Response(
            200, json=load_fixture("open_meteo_geocoding/search_bangkok.json")
        )
    )
    assert (
        client.post(GEOCODE_PATH, json={"query": "Bangkok"}, headers=AUTH).status_code
        == 200
    )


def response_text(body: dict[str, object]) -> str:
    import json

    return json.dumps(body)
