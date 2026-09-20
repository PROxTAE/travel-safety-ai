"""Contract tests for POST /internal/v1/transport/query.

The property this file exists to protect: an empty list must mean "no trips are
running here", and a query outside every registered feed must not look like one.
Transit coverage is per agency and never global, so those two answers are much
easier to confuse than for a worldwide hazard feed.

Second, and just as dangerous: a running trip with no matched timetable must
report UNKNOWN. Contract § 3.6 forbids inferring ON_TIME from the absence of an
alert, and roughly two thirds of live trips are in exactly that state.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import FIXTURE_ROOT, TEST_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
PATH = "/internal/v1/transport/query"
RT_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace"
STATIC_URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"

FIXTURES = FIXTURE_ROOT / "gtfs_mta"
NEW_YORK = [-74.1, 40.6, -73.8, 40.9]
BANGKOK = [100.0, 13.0, 101.0, 14.0]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def _mock_feeds(schedule: bytes | None = None, realtime: bytes | None = None) -> None:
    respx.get(STATIC_URL).mock(
        return_value=httpx.Response(
            200,
            content=schedule
            if schedule is not None
            else (FIXTURES / "mta_subway_ace_static.zip").read_bytes(),
            headers={"Content-Type": "application/zip"},
        )
    )
    respx.get(RT_URL).mock(
        return_value=httpx.Response(
            200,
            content=realtime
            if realtime is not None
            else (FIXTURES / "mta_subway_ace_tripupdates.pb").read_bytes(),
            headers={"Content-Type": "application/x-protobuf"},
        )
    )


def _query(**kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"bbox": NEW_YORK, "limit": 100}
    body.update(kw)
    return body


# -------------------------------------------------------------- happy path


@respx.mock
def test_live_trips_come_back_with_stops_and_times(client: TestClient) -> None:
    _mock_feeds()
    response = client.post(PATH, headers=AUTH, json=_query())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["statuses"]
    first = data["statuses"][0]
    assert first["origin_stop"]["name"]
    assert first["destination_stop"]["name"]
    assert first["estimated_arrival"]
    assert data["attribution"]


@respx.mock
def test_the_answer_says_how_many_trips_matched_a_timetable(
    client: TestClient,
) -> None:
    """Most statuses are UNKNOWN by nature. A consumer seeing that should be
    able to tell it is the schedule join and not a broken feed."""
    _mock_feeds()
    data = client.post(PATH, headers=AUTH, json=_query()).json()["data"]

    assert data["trips_matched_to_schedule"] > 0
    assert data["trips_without_schedule"] > 0
    assert data["trips_matched_to_schedule"] + data["trips_without_schedule"] == len(
        data["statuses"]
    )


@respx.mock
def test_an_unmatched_trip_is_unknown_and_never_on_time(client: TestClient) -> None:
    """The § 3.6 invariant, checked through the wire format."""
    _mock_feeds()
    statuses = client.post(PATH, headers=AUTH, json=_query()).json()["data"]["statuses"]

    unmatched = [s for s in statuses if s["scheduled_arrival"] is None]
    assert unmatched
    for status in unmatched:
        assert status["status"] == "UNKNOWN"
        assert status["delay_minutes"] is None


@respx.mock
def test_a_delay_is_minutes_not_a_timezone_offset(client: TestClient) -> None:
    """Reading a New York timetable as UTC made every train 250 minutes late -
    a number plausible enough to ship."""
    _mock_feeds()
    statuses = client.post(PATH, headers=AUTH, json=_query()).json()["data"]["statuses"]

    measured = [s for s in statuses if s["delay_minutes"] is not None]
    assert measured
    for status in measured:
        assert abs(status["delay_minutes"]) < 120


@respx.mock
def test_every_status_carries_provenance_and_quality(client: TestClient) -> None:
    _mock_feeds()
    statuses = client.post(PATH, headers=AUTH, json=_query()).json()["data"]["statuses"]

    for status in statuses:
        assert status["source"]["provider"] == "gtfs_registry"
        assert status["source"]["license"]
        assert status["quality"]["status"]
        assert status["feed_id"] == "mta_nyct_subway"


# --------------------------------------------------------------- coverage


@respx.mock
def test_a_region_with_no_registered_feed_is_unsupported_not_empty(
    client: TestClient,
) -> None:
    """The failure that matters. An empty list here reads as "no trains are
    running", when the truth is "nobody registered a feed for Bangkok"."""
    _mock_feeds()
    response = client.post(PATH, headers=AUTH, json=_query(bbox=BANGKOK))

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_COVERAGE"
    assert body["error"]["retryable"] is False


@respx.mock
def test_a_route_nobody_is_running_is_an_empty_list_not_an_error(
    client: TestClient,
) -> None:
    """Inside a covered region, nothing running is a real answer."""
    _mock_feeds()
    response = client.post(PATH, headers=AUTH, json=_query(route_ids=["ZZZ"]))

    assert response.status_code == 200
    assert response.json()["data"]["statuses"] == []


# ------------------------------------------------------------- degradation


@respx.mock
def test_a_missing_schedule_still_returns_live_trips(client: TestClient) -> None:
    """A realtime snapshot is worth having without a timetable. Failing the
    request because a 5 MB archive was slow would lose usable live data."""
    respx.get(STATIC_URL).mock(return_value=httpx.Response(503))
    respx.get(RT_URL).mock(
        return_value=httpx.Response(
            200, content=(FIXTURES / "mta_subway_ace_tripupdates.pb").read_bytes()
        )
    )

    response = client.post(PATH, headers=AUTH, json=_query())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["statuses"]
    assert data["trips_matched_to_schedule"] == 0
    assert all(s["status"] == "UNKNOWN" for s in data["statuses"])


@respx.mock
def test_a_realtime_feed_that_is_not_protobuf_is_reported_not_guessed(
    client: TestClient,
) -> None:
    _mock_feeds(realtime=b"<html>scheduled maintenance</html>")
    response = client.post(PATH, headers=AUTH, json=_query())

    assert response.status_code >= 400
    assert response.json()["error"]["code"] != "INTERNAL_ERROR"


# ------------------------------------------------------------- validation


def test_transport_requires_internal_auth(client: TestClient) -> None:
    assert client.post(PATH, json=_query()).status_code == 401


def test_a_swapped_bbox_is_rejected(client: TestClient) -> None:
    response = client.post(PATH, headers=AUTH, json=_query(bbox=[13.0, 100.0, 14.0, 101.0]))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_an_unknown_field_is_refused(client: TestClient) -> None:
    response = client.post(PATH, headers=AUTH, json={"bbox": NEW_YORK, "agency": "MTA"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
