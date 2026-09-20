"""Trip CRUD over HTTP against a real PostgreSQL.

The behaviours here are the ones a reviewer cannot confirm by reading the handler: that a trip
belonging to somebody else is indistinguishable from one that does not exist, that a stale
`If-Match` is refused by the database rather than by whichever request read first, that changing a
destination throws away the assessment made for the old one, and that a page boundary hides no row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]


@pytest.fixture(scope="module")
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture
def authed_app(live_app: FastAPI, key: SigningKeyPair) -> FastAPI:
    live_app.state.jwks = StubJwks.containing(key)
    return live_app


@pytest.fixture
async def client(authed_app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=authed_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def token(key: SigningKeyPair) -> str:
    """One fresh user per test, so tests cannot see each other's trips."""
    return key.sign({"sub": f"phase4-{uuid.uuid4()}"})


@pytest.fixture
def other_token(key: SigningKeyPair) -> str:
    return key.sign({"sub": f"phase4-other-{uuid.uuid4()}"})


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def place(name: str, lon: float, lat: float, *, confirmed: bool = True) -> dict[str, Any]:
    return {
        "place_id": f"omg-{name.lower()}",
        "display_name": name,
        "coordinates": {"type": "Point", "coordinates": [lon, lat]},
        "country_code": "TH",
        "timezone": "Asia/Bangkok",
        "provider": "open_meteo",
        "confirmed_by_user": confirmed,
    }


def trip_body(**overrides: Any) -> dict[str, Any]:
    departure = datetime.now(UTC) + timedelta(days=7)
    body: dict[str, Any] = {
        "title": "Bangkok to Chiang Mai",
        "origin": place("Bangkok", 100.5018, 13.7563),
        "destination": place("Chiang Mai", 98.9853, 18.7883),
        "departure_time": departure.isoformat(),
        "return_time": (departure + timedelta(days=3)).isoformat(),
        "timezone": "Asia/Bangkok",
        "travel_modes": ["TRAIN"],
    }
    body.update(overrides)
    return body


async def create(client: httpx.AsyncClient, token: str, **overrides: Any) -> httpx.Response:
    return await client.post("/api/v1/trips", headers=auth(token), json=trip_body(**overrides))


# --- create ---------------------------------------------------------------------------------------


async def test_a_trip_is_created_at_revision_one(client: httpx.AsyncClient, token: str) -> None:
    response = await create(client, token)

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["revision"] == 1
    assert data["status"] == "DRAFT"
    assert response.headers["ETag"] == 'W/"1"'
    assert response.headers["Location"] == f"/api/v1/trips/{data['trip_id']}"


async def test_the_stored_trip_keeps_the_provider_that_resolved_the_place(
    client: httpx.AsyncClient, token: str
) -> None:
    """Provenance is why LocationRef is stored whole rather than split into columns."""
    response = await create(client, token)

    assert response.json()["data"]["origin"]["provider"] == "open_meteo"


async def test_an_unconfirmed_origin_is_refused(client: httpx.AsyncClient, token: str) -> None:
    response = await create(client, token, origin=place("Bangkok", 100.5, 13.7, confirmed=False))

    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [item["path"] for item in error["field_errors"]] == ["origin.confirmed_by_user"]
    assert error["field_errors"][0]["code"] == "NOT_CONFIRMED"


async def test_a_swapped_coordinate_pair_is_refused(
    client: httpx.AsyncClient, token: str
) -> None:
    """Bangkok is [100.5, 13.75]. Reversed, the latitude is 100.5, which is not a latitude.

    Without the per-element bound this would validate and quietly relocate the trip.
    """
    response = await create(client, token, origin=place("Bangkok", 13.7563, 100.5018))

    assert response.status_code == 400, response.text


async def test_a_naive_timestamp_is_refused(client: httpx.AsyncClient, token: str) -> None:
    """Assuming UTC would shift a Bangkok departure by seven hours."""
    response = await create(client, token, departure_time="2027-01-01T09:30:00")

    assert response.status_code == 400, response.text


async def test_a_mode_with_no_data_source_is_unprocessable(
    client: httpx.AsyncClient, token: str
) -> None:
    """422 and `UNSUPPORTED_COVERAGE`, distinct from a malformed request.

    The difference tells the client whether editing the form could help.
    """
    response = await create(client, token, travel_modes=["FLIGHT"])

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "UNSUPPORTED_COVERAGE"


async def test_a_client_cannot_set_the_revision(client: httpx.AsyncClient, token: str) -> None:
    """`extra="forbid"`: a field the server owns is reported, not silently dropped."""
    response = await client.post(
        "/api/v1/trips", headers=auth(token), json={**trip_body(), "revision": 99}
    )

    assert response.status_code == 400, response.text


async def test_a_client_cannot_preselect_a_route(client: httpx.AsyncClient, token: str) -> None:
    response = await client.post(
        "/api/v1/trips",
        headers=auth(token),
        json={**trip_body(), "selected_route_id": str(uuid.uuid4())},
    )

    assert response.status_code == 400, response.text


# --- idempotency ------------------------------------------------------------------------------


async def test_the_same_key_and_body_returns_the_same_trip(
    client: httpx.AsyncClient, token: str
) -> None:
    """The case this exists for: a create that timed out on the network and was retried."""
    body = trip_body()
    headers = {**auth(token), "Idempotency-Key": f"key-{uuid.uuid4()}"}

    first = await client.post("/api/v1/trips", headers=headers, json=body)
    second = await client.post("/api/v1/trips", headers=headers, json=body)

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"]["trip_id"] == second.json()["data"]["trip_id"]


async def test_the_same_key_with_a_different_body_is_a_conflict(
    client: httpx.AsyncClient, token: str
) -> None:
    headers = {**auth(token), "Idempotency-Key": f"key-{uuid.uuid4()}"}

    await client.post("/api/v1/trips", headers=headers, json=trip_body())
    second = await client.post(
        "/api/v1/trips", headers=headers, json=trip_body(title="Somewhere else")
    )

    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_key_order_in_the_body_does_not_make_a_conflict(
    client: httpx.AsyncClient, token: str
) -> None:
    """Two serialisations of the same request are the same request."""
    body = trip_body()
    reordered = dict(reversed(list(body.items())))
    headers = {**auth(token), "Idempotency-Key": f"key-{uuid.uuid4()}"}

    first = await client.post("/api/v1/trips", headers=headers, json=body)
    second = await client.post("/api/v1/trips", headers=headers, json=reordered)

    assert second.status_code == 200, second.text
    assert first.json()["data"]["trip_id"] == second.json()["data"]["trip_id"]


async def test_two_users_may_use_the_same_key(
    client: httpx.AsyncClient, token: str, other_token: str
) -> None:
    """Keys are scoped per user; short client-generated keys collide otherwise."""
    shared = f"key-{uuid.uuid4()}"

    mine = await client.post(
        "/api/v1/trips", headers={**auth(token), "Idempotency-Key": shared}, json=trip_body()
    )
    theirs = await client.post(
        "/api/v1/trips",
        headers={**auth(other_token), "Idempotency-Key": shared},
        json=trip_body(),
    )

    assert mine.status_code == 201, mine.text
    assert theirs.status_code == 201, theirs.text
    assert mine.json()["data"]["trip_id"] != theirs.json()["data"]["trip_id"]


# --- read and ownership -------------------------------------------------------------------------


async def test_a_trip_can_be_read_back_with_its_etag(
    client: httpx.AsyncClient, token: str
) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.get(f"/api/v1/trips/{trip_id}", headers=auth(token))

    assert response.status_code == 200, response.text
    assert response.headers["ETag"] == 'W/"1"'


async def test_another_users_trip_is_reported_as_not_found(
    client: httpx.AsyncClient, token: str, other_token: str
) -> None:
    """404 rather than 403. A 403 would confirm the id exists, which is all an enumerator needs."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.get(f"/api/v1/trips/{trip_id}", headers=auth(other_token))

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_an_unknown_trip_gives_the_same_answer(
    client: httpx.AsyncClient, token: str
) -> None:
    """Identical to the previous case on purpose: the two must not be distinguishable."""
    response = await client.get(f"/api/v1/trips/{uuid.uuid4()}", headers=auth(token))

    assert response.status_code == 404, response.text


async def test_a_trip_cannot_be_read_without_a_token(
    client: httpx.AsyncClient, token: str
) -> None:
    created = await create(client, token)

    response = await client.get(f"/api/v1/trips/{created.json()['data']['trip_id']}")

    assert response.status_code == 401, response.text


# --- update and concurrency ---------------------------------------------------------------------


async def test_an_update_increments_the_revision(client: httpx.AsyncClient, token: str) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"title": "Renamed"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["revision"] == 2
    assert response.headers["ETag"] == 'W/"2"'


async def test_an_update_without_if_match_is_refused(
    client: httpx.AsyncClient, token: str
) -> None:
    """428, so the client knows the request would be accepted with the header."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.patch(
        f"/api/v1/trips/{trip_id}", headers=auth(token), json={"title": "Renamed"}
    )

    assert response.status_code == 428, response.text
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_a_stale_revision_is_refused(client: httpx.AsyncClient, token: str) -> None:
    """The second tab's overwrite. This is the whole reason `revision` exists."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"title": "First edit"},
    )
    second = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"title": "Second edit, from a tab that never saw the first"},
    )

    assert second.status_code == 412, second.text

    current = await client.get(f"/api/v1/trips/{trip_id}", headers=auth(token))
    assert current.json()["data"]["title"] == "First edit"


async def test_if_match_star_is_refused(client: httpx.AsyncClient, token: str) -> None:
    """`*` means "whatever is current" — exactly the unconditional overwrite this prevents."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": "*"},
        json={"title": "Forced"},
    )

    assert response.status_code == 412, response.text


async def test_an_empty_patch_does_not_burn_a_revision(
    client: httpx.AsyncClient, token: str
) -> None:
    """A client that computed an empty diff gets the trip back, not an error."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.patch(
        f"/api/v1/trips/{trip_id}", headers={**auth(token), "If-Match": 'W/"1"'}, json={}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["revision"] == 1


async def test_a_patch_leaves_unsent_fields_alone(client: httpx.AsyncClient, token: str) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]
    original = created.json()["data"]

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"title": "Renamed"},
    )

    data = response.json()["data"]
    assert data["timezone"] == original["timezone"]
    assert data["travel_modes"] == original["travel_modes"]
    assert data["departure_time"] == original["departure_time"]


async def test_a_null_return_time_clears_the_return_leg(
    client: httpx.AsyncClient, token: str
) -> None:
    """`exclude_unset`, not `exclude_none`: sending null is an instruction."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"return_time": None},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["return_time"] is None


async def test_a_patch_is_validated_against_the_merged_journey(
    client: httpx.AsyncClient, token: str
) -> None:
    """Changing only the return time can still put it before a departure never mentioned."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]
    earlier = datetime.now(UTC) + timedelta(days=1)

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"return_time": earlier.isoformat()},
    )

    assert response.status_code == 400, response.text
    assert [item["path"] for item in response.json()["error"]["field_errors"]] == ["return_time"]


async def test_another_users_trip_cannot_be_updated(
    client: httpx.AsyncClient, token: str, other_token: str
) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(other_token), "If-Match": 'W/"1"'},
        json={"title": "Not mine"},
    )

    assert response.status_code == 404, response.text


async def test_a_forbidden_status_transition_is_refused(
    client: httpx.AsyncClient, token: str
) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"status": "COMPLETED"},
    )

    assert response.status_code == 400, response.text


async def test_a_completed_trip_can_no_longer_be_edited(
    client: httpx.AsyncClient, token: str
) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    for revision, new_status in ((1, "PLANNED"), (2, "ACTIVE"), (3, "COMPLETED")):
        moved = await client.patch(
            f"/api/v1/trips/{trip_id}",
            headers={**auth(token), "If-Match": f'W/"{revision}"'},
            json={"status": new_status},
        )
        assert moved.status_code == 200, moved.text

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"4"'},
        json={"title": "Reopened"},
    )

    assert response.status_code == 400, response.text


# --- assessment invalidation ----------------------------------------------------------------------


async def test_changing_the_destination_drops_the_previous_assessment(
    client: httpx.AsyncClient, token: str, db_session: Any
) -> None:
    """The most dangerous stale value this service can hold.

    A verdict reached for Chiang Mai, still displayed after the traveller changed the destination
    to Phuket, looks exactly like a current answer.
    """
    from sqlalchemy import text

    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    # Stand in for phase 5 having started an assessment for this trip.
    await db_session.execute(
        text("UPDATE travel.trips SET latest_request_id = :rid WHERE id = :tid"),
        {"rid": str(uuid.uuid4()), "tid": trip_id},
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"destination": place("Phuket", 98.3381, 7.8804)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["latest_request_id"] is None


async def test_renaming_a_trip_keeps_its_assessment(
    client: httpx.AsyncClient, token: str, db_session: Any
) -> None:
    """The verdict still applies; throwing it away would cost a real provider call for nothing."""
    from sqlalchemy import text

    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]
    request_id = str(uuid.uuid4())

    await db_session.execute(
        text("UPDATE travel.trips SET latest_request_id = :rid WHERE id = :tid"),
        {"rid": request_id, "tid": trip_id},
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/trips/{trip_id}",
        headers={**auth(token), "If-Match": 'W/"1"'},
        json={"title": "A better name"},
    )

    assert response.json()["data"]["latest_request_id"] == request_id


# --- list and pagination ------------------------------------------------------------------------


async def test_only_the_callers_trips_are_listed(
    client: httpx.AsyncClient, token: str, other_token: str
) -> None:
    await create(client, token)
    await create(client, other_token)

    response = await client.get("/api/v1/trips", headers=auth(token))

    assert response.status_code == 200, response.text
    assert len(response.json()["data"]) == 1


async def test_trips_come_back_newest_departure_first(
    client: httpx.AsyncClient, token: str
) -> None:
    base = datetime.now(UTC) + timedelta(days=2)
    for offset in (0, 10, 5):
        await create(
            client,
            token,
            departure_time=(base + timedelta(days=offset)).isoformat(),
            return_time=None,
        )

    response = await client.get("/api/v1/trips", headers=auth(token))

    departures = [item["departure_time"] for item in response.json()["data"]]
    assert departures == sorted(departures, reverse=True)


async def test_paging_returns_every_row_exactly_once(
    client: httpx.AsyncClient, token: str
) -> None:
    """The bug keyset pagination exists to avoid: a boundary that hides or repeats a row."""
    base = datetime.now(UTC) + timedelta(days=2)
    for offset in range(5):
        await create(
            client,
            token,
            departure_time=(base + timedelta(days=offset)).isoformat(),
            return_time=None,
        )

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = await client.get("/api/v1/trips", headers=auth(token), params=params)
        body = page.json()
        seen.extend(item["trip_id"] for item in body["data"])
        cursor = body["page"]["next_cursor"]
        if not body["page"]["has_more"]:
            break

    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_trips_leaving_at_the_same_moment_do_not_confuse_the_cursor(
    client: httpx.AsyncClient, token: str
) -> None:
    """The reason the key is `(departure_time, id)` and not the timestamp alone."""
    departure = (datetime.now(UTC) + timedelta(days=4)).isoformat()
    for _ in range(3):
        await create(client, token, departure_time=departure, return_time=None)

    first = await client.get("/api/v1/trips", headers=auth(token), params={"limit": 2})
    second = await client.get(
        "/api/v1/trips",
        headers=auth(token),
        params={"limit": 2, "cursor": first.json()["page"]["next_cursor"]},
    )

    ids = [item["trip_id"] for item in first.json()["data"] + second.json()["data"]]
    assert len(set(ids)) == 3


async def test_a_handmade_cursor_is_rejected(client: httpx.AsyncClient, token: str) -> None:
    response = await client.get(
        "/api/v1/trips", headers=auth(token), params={"cursor": "not-a-cursor"}
    )

    assert response.status_code == 400, response.text
    assert [item["path"] for item in response.json()["error"]["field_errors"]] == ["cursor"]


async def test_an_unknown_status_filter_is_rejected(
    client: httpx.AsyncClient, token: str
) -> None:
    response = await client.get(
        "/api/v1/trips", headers=auth(token), params={"status": "GOING_WELL"}
    )

    assert response.status_code == 400, response.text


# --- delete ---------------------------------------------------------------------------------------


async def test_a_deleted_trip_reports_work_still_outstanding(
    client: httpx.AsyncClient, token: str
) -> None:
    """`IN_PROGRESS`, not `COMPLETED`: other services still hold records for this trip."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.delete(f"/api/v1/trips/{trip_id}", headers=auth(token))

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "IN_PROGRESS"
    assert data["completed_at"] is None


async def test_a_deleted_trip_disappears_from_the_list(
    client: httpx.AsyncClient, token: str
) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]
    await client.delete(f"/api/v1/trips/{trip_id}", headers=auth(token))

    listed = await client.get("/api/v1/trips", headers=auth(token))

    assert [item["trip_id"] for item in listed.json()["data"]] == []


async def test_a_deleted_trip_can_still_be_asked_for_explicitly(
    client: httpx.AsyncClient, token: str
) -> None:
    """Inside the retention window a person can still see what they removed."""
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]
    await client.delete(f"/api/v1/trips/{trip_id}", headers=auth(token))

    listed = await client.get("/api/v1/trips", headers=auth(token), params={"status": "DELETED"})

    assert [item["trip_id"] for item in listed.json()["data"]] == [trip_id]


async def test_deleting_twice_is_not_found_the_second_time(
    client: httpx.AsyncClient, token: str
) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    await client.delete(f"/api/v1/trips/{trip_id}", headers=auth(token))
    second = await client.delete(f"/api/v1/trips/{trip_id}", headers=auth(token))

    assert second.status_code == 404, second.text


async def test_another_users_trip_cannot_be_deleted(
    client: httpx.AsyncClient, token: str, other_token: str
) -> None:
    created = await create(client, token)
    trip_id = created.json()["data"]["trip_id"]

    response = await client.delete(f"/api/v1/trips/{trip_id}", headers=auth(other_token))

    assert response.status_code == 404, response.text

    still_there = await client.get(f"/api/v1/trips/{trip_id}", headers=auth(token))
    assert still_there.status_code == 200
