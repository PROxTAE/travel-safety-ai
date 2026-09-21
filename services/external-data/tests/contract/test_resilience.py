"""Phase 7 verification: what happens when providers misbehave.

The module plan asks for 429, timeout, malformed payload, stale data, and a
primary failure with a backup available. Each is simulated against the real
adapters and the real transport, because the interesting question is not
whether an exception is raised but what a caller receives - and for a safety
service, a wrong-but-plausible answer is worse than an error.

The property behind every test here: an empty list must always mean "nothing
was reported", never "we could not find out".
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.domain.errors import ProviderError, ProviderErrorCode
from app.main import create_app
from tests.conftest import TEST_TOKEN, load_fixture

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
DISASTERS = "/internal/v1/disasters/query"
WEATHER = "/internal/v1/weather/query"
CONTEXT = "/internal/v1/context/query"

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

BANGKOK_SAMPLE = {"latitude": 13.7563, "longitude": 100.5018}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def _healthy_hazards() -> None:
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("usgs/significant_month.json"))
    )
    respx.get(GDACS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("gdacs/eventlist_eq.json"))
    )
    respx.get(EONET_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("eonet/events.json"))
    )


# --------------------------------------------------------------------- 429


@respx.mock
def test_a_rate_limited_provider_is_retryable_and_says_when(
    client: TestClient,
) -> None:
    """A 429 with Retry-After is the one failure where the caller can do
    something useful, so the number has to survive to them."""
    respx.get(FORECAST_URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "37"}, json={})
    )

    response = client.post(WEATHER, headers=AUTH, json={"samples": [BANGKOK_SAMPLE]})

    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["retryable"] is True
    assert error["retry_after_seconds"] == 37


@respx.mock
def test_one_rate_limited_hazard_source_does_not_lose_the_others(
    client: TestClient,
) -> None:
    """The sources are complementary. Losing all hazards because one was
    throttled would turn a partial answer into no answer."""
    _healthy_hazards()
    respx.get(GDACS_URL).mock(return_value=httpx.Response(429, json={}))

    response = client.post(DISASTERS, headers=AUTH, json={})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["events"]
    assert "gdacs" in body["meta"]["degraded_services"]
    assert "gdacs" not in body["data"]["sources"]


# ----------------------------------------------------------------- timeout


@respx.mock
def test_a_timeout_is_reported_as_a_timeout_not_as_no_data(
    client: TestClient,
) -> None:
    respx.get(FORECAST_URL).mock(side_effect=httpx.ReadTimeout("too slow"))

    response = client.post(WEATHER, headers=AUTH, json={"samples": [BANGKOK_SAMPLE]})

    assert response.status_code in (504, 503)
    assert response.json()["error"]["code"] in (
        "DEPENDENCY_TIMEOUT",
        "DEPENDENCY_UNAVAILABLE",
    )


@respx.mock
def test_every_hazard_source_timing_out_is_an_error_not_an_empty_list(
    client: TestClient,
) -> None:
    """The single most dangerous failure this service can have.

    `events: []` reads as "no hazards near you". If the reason is that nothing
    could be reached, the caller must be told, not reassured.
    """
    for url in (USGS_URL, GDACS_URL, EONET_URL):
        respx.get(url).mock(side_effect=httpx.ReadTimeout("too slow"))

    response = client.post(DISASTERS, headers=AUTH, json={})

    assert response.status_code >= 400
    assert response.json().get("data") is None


# ------------------------------------------------------- malformed payload


@respx.mock
def test_a_payload_that_is_not_json_is_a_provider_problem_not_a_500(
    client: TestClient,
) -> None:
    respx.get(FORECAST_URL).mock(
        return_value=httpx.Response(200, content=b"<html>maintenance</html>")
    )

    response = client.post(WEATHER, headers=AUTH, json={"samples": [BANGKOK_SAMPLE]})

    assert response.status_code != 500
    assert response.json()["error"]["code"] != "INTERNAL_ERROR"


@respx.mock
def test_json_with_the_wrong_shape_is_detected_rather_than_half_read(
    client: TestClient,
) -> None:
    """Schema drift has to surface. Silently normalising whatever fields did
    survive would produce records that look fine and are missing half the
    hazard."""
    _healthy_hazards()
    respx.get(USGS_URL).mock(
        return_value=httpx.Response(200, json={"type": "Something", "features": "no"})
    )

    response = client.post(DISASTERS, headers=AUTH, json={})

    assert response.status_code == 200
    body = response.json()
    assert "usgs_earthquake" in body["meta"]["degraded_services"]
    # The other two still answered.
    assert body["data"]["events"]


@respx.mock
def test_an_empty_body_is_not_read_as_no_hazards(client: TestClient) -> None:
    for url in (USGS_URL, GDACS_URL, EONET_URL):
        respx.get(url).mock(return_value=httpx.Response(200, content=b""))

    response = client.post(DISASTERS, headers=AUTH, json={})

    assert response.status_code >= 400


# ------------------------------------------------------------------- stale


@respx.mock
def test_stale_data_is_served_but_labelled(client: TestClient) -> None:
    """Shared context § 10 allows a stale read with a warning. What it does not
    allow is serving it as current."""
    _healthy_hazards()

    body = client.post(DISASTERS, headers=AUTH, json={}).json()

    statuses = {event["quality"]["status"] for event in body["data"]["events"]}
    assert statuses
    # The captured feeds were generated well over the ten-minute budget ago.
    assert "STALE" in statuses
    for event in body["data"]["events"]:
        if event["quality"]["status"] == "STALE":
            assert event["quality"]["notes"]


# -------------------------------------------- primary fails, others survive


@respx.mock
def test_a_capability_failing_does_not_take_the_combined_context_with_it(
    client: TestClient,
) -> None:
    """The reason /context/query fans out instead of chaining."""
    _healthy_hazards()
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(503, json={}))

    response = client.post(
        CONTEXT,
        headers=AUTH,
        json={"samples": [BANGKOK_SAMPLE], "deadline_seconds": 20},
    )

    assert response.status_code == 200
    body = response.json()
    capabilities = {c["capability"]: c for c in body["data"]["capabilities"]}
    assert capabilities["WEATHER"]["outcome"] == "FAILED"
    assert capabilities["DISASTER"]["outcome"] == "ANSWERED"
    assert body["data"]["disaster_events"]


@respx.mock
def test_a_failure_message_never_reaches_the_caller_verbatim(
    client: TestClient,
) -> None:
    """A provider error can name an upstream, a key or an internal host. The
    caller learns the contract code and nothing else."""
    respx.get(FORECAST_URL).mock(
        return_value=httpx.Response(
            401, json={"reason": "Invalid api key sk-live-abc123 for tenant 42"}
        )
    )

    response = client.post(WEATHER, headers=AUTH, json={"samples": [BANGKOK_SAMPLE]})

    text = response.text
    assert "sk-live-abc123" not in text
    assert "api key" not in text.lower()
    assert "open-meteo" not in text.lower()


# ---------------------------------------------------------------- envelope


@respx.mock
@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 408, 429, 500, 503])
def test_every_provider_status_produces_a_contract_error(
    client: TestClient, status_code: int
) -> None:
    """No provider status may escape as an unshaped 500."""
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(status_code, json={}))

    response = client.post(WEATHER, headers=AUTH, json={"samples": [BANGKOK_SAMPLE]})
    body = response.json()

    assert "error" in body
    assert body["error"]["code"]
    assert body["meta"]["contract_version"] == "1.0.0"
    assert body["meta"]["request_id"]


@respx.mock
def test_an_oversized_body_does_not_take_the_service_down(
    client: TestClient,
) -> None:
    """A provider that starts streaming megabytes must not be able to exhaust
    this process."""
    payload: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    payload["features"] = [
        {
            "type": "Feature",
            "id": f"x{i}",
            "properties": {"mag": 1.0, "time": 1789000000000, "place": "x" * 200},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0, 0.0]},
        }
        for i in range(5000)
    ]
    _healthy_hazards()
    respx.get(USGS_URL).mock(return_value=httpx.Response(200, json=payload))

    response = client.post(DISASTERS, headers=AUTH, json={})

    assert response.status_code == 200


# ------------------------------- nothing answered, for different reasons


def test_an_unreachable_source_outranks_a_source_that_does_not_cover_it() -> None:
    """Which failure gets reported when no hazard source answered.

    "Nobody publishes this" is 422 with `retryable: false`; "we could not reach
    anybody" is a 5xx the caller should retry. The endpoint used to report
    whichever error came *last* in iteration order, so the answer depended on
    where a provider happened to sit in the registry file.

    Tested at this level deliberately. With today's three sources the wrong
    branch is not reachable through the API - every event type EONET declines,
    GDACS declines too, so a coverage answer can never be the last one while a
    real failure is present. That is a property of today's registry, not of the
    code, and it stops being true the moment a fourth source is added or the
    file is reordered. The two end-to-end tests below cover what is reachable
    now; this one covers the rule itself.
    """
    from app.api.internal import _why_nothing_answered

    timed_out = ProviderError(ProviderErrorCode.PROVIDER_TIMEOUT, "gdacs")
    not_covered = ProviderError(ProviderErrorCode.OUTSIDE_COVERAGE, "nasa_eonet")

    # The failure wins from either position, which is the whole point.
    assert _why_nothing_answered([not_covered, timed_out]) is timed_out
    assert _why_nothing_answered([timed_out, not_covered]) is timed_out


def test_coverage_is_the_answer_only_when_every_source_gave_it() -> None:
    from app.api.internal import _why_nothing_answered

    first = ProviderError(ProviderErrorCode.OUTSIDE_COVERAGE, "usgs_earthquake")
    second = ProviderError(ProviderErrorCode.OUTSIDE_COVERAGE, "nasa_eonet")

    assert _why_nothing_answered([first, second]) is first


@respx.mock
def test_every_source_saying_not_covered_is_still_a_coverage_answer(
    client: TestClient,
) -> None:
    """The other half: when nothing failed and every source simply does not
    publish what was asked for, that is a real answer and not a retry."""
    for url in (USGS_URL, GDACS_URL, EONET_URL):
        respx.get(url).mock(
            return_value=httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        )

    response = client.post(DISASTERS, headers=AUTH, json={"event_types": ["TRANSPORT_CLOSURE"]})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_COVERAGE"
    assert error["retryable"] is False


@respx.mock
def test_one_source_answering_still_wins_over_any_failure(
    client: TestClient,
) -> None:
    """A partial answer is an answer. Two sources down must not turn one
    source's real data into an error."""
    _healthy_hazards()
    respx.get(GDACS_URL).mock(side_effect=httpx.ReadTimeout("down"))
    respx.get(EONET_URL).mock(side_effect=httpx.ReadTimeout("down"))

    response = client.post(DISASTERS, headers=AUTH, json={})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["events"]
    assert body["data"]["sources"] == ["usgs_earthquake"]
    assert set(body["meta"]["degraded_services"]) == {"gdacs", "nasa_eonet"}
