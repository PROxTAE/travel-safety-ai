"""Two requests arriving at once.

Everything here runs against a real PostgreSQL with real concurrent transactions, because that is
the only place these guarantees exist. A test that serialised the two requests would pass against
an implementation that reads, thinks, and then writes — which is exactly the implementation that
loses an edit in production.

Each test opens its own session so the two operations are genuinely separate transactions.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.db.engine import session_scope
from app.repositories import idempotency, trips
from tests.database import requires_database

pytestmark = [pytest.mark.integration, requires_database]


def place(name: str, lon: float, lat: float) -> dict[str, Any]:
    return {
        "place_id": f"omg-{name.lower()}",
        "display_name": name,
        "coordinates": {"type": "Point", "coordinates": [lon, lat]},
        "country_code": "TH",
        "timezone": "Asia/Bangkok",
        "provider": "open_meteo",
        "confirmed_by_user": True,
    }


def trip_values() -> dict[str, Any]:
    departure = datetime.now(UTC) + timedelta(days=7)
    return {
        "title": "Concurrency",
        "origin": place("Bangkok", 100.5018, 13.7563),
        "destination": place("Chiang Mai", 98.9853, 18.7883),
        "departure_time": departure,
        "return_time": None,
        "timezone": "Asia/Bangkok",
        "travel_modes": ["TRAIN"],
        "preferences": {},
        "status": "DRAFT",
    }


@pytest.fixture
async def owner_id(live_app: FastAPI) -> uuid.UUID:
    """A real profile row, since trips carry a foreign key to it."""
    async with session_scope(live_app.state.session_factory) as session:
        from app.repositories import user_profiles

        profile = await user_profiles.get_or_create_by_subject(
            session,
            subject_id=f"concurrency-{uuid.uuid4()}",
            default_locale="en-US",
            default_timezone="UTC",
        )
        return profile.id


async def test_only_one_of_two_simultaneous_updates_wins(
    live_app: FastAPI, owner_id: uuid.UUID
) -> None:
    """The second tab's overwrite, as it actually happens: both read revision 1, both then write.

    A read-then-write implementation passes a sequential test and fails this one.
    """
    async with session_scope(live_app.state.session_factory) as session:
        created = await trips.create(session, owner_id=owner_id, values=trip_values())
        trip_id = created.id

    async def edit(title: str) -> Any:
        async with session_scope(live_app.state.session_factory) as session:
            return await trips.bump(
                session,
                owner_id=owner_id,
                trip_id=trip_id,
                expected_revision=1,
                values={"title": title},
            )

    first, second = await asyncio.gather(edit("from tab one"), edit("from tab two"))

    winners = [result for result in (first, second) if result is not None]
    assert len(winners) == 1, "both writes were accepted; one edit was silently lost"
    assert winners[0].revision == 2


async def test_the_loser_can_retry_after_re_reading(
    live_app: FastAPI, owner_id: uuid.UUID
) -> None:
    """412 is only useful if the documented recovery actually works."""
    async with session_scope(live_app.state.session_factory) as session:
        created = await trips.create(session, owner_id=owner_id, values=trip_values())
        trip_id = created.id

    async with session_scope(live_app.state.session_factory) as session:
        await trips.bump(
            session, owner_id=owner_id, trip_id=trip_id, expected_revision=1, values={"title": "A"}
        )

    async with session_scope(live_app.state.session_factory) as session:
        stale = await trips.bump(
            session, owner_id=owner_id, trip_id=trip_id, expected_revision=1, values={"title": "B"}
        )
        assert stale is None

    async with session_scope(live_app.state.session_factory) as session:
        current = await trips.get_owned(session, owner_id=owner_id, trip_id=trip_id)
        assert current is not None
        retried = await trips.bump(
            session,
            owner_id=owner_id,
            trip_id=trip_id,
            expected_revision=current.revision,
            values={"title": "B"},
        )

    assert retried is not None
    assert retried.title == "B"
    assert retried.revision == 3


async def test_a_revision_never_goes_backwards(live_app: FastAPI, owner_id: uuid.UUID) -> None:
    """Ten concurrent edits, each claiming revision 1. Exactly one may succeed."""
    async with session_scope(live_app.state.session_factory) as session:
        created = await trips.create(session, owner_id=owner_id, values=trip_values())
        trip_id = created.id

    async def edit(index: int) -> Any:
        async with session_scope(live_app.state.session_factory) as session:
            return await trips.bump(
                session,
                owner_id=owner_id,
                trip_id=trip_id,
                expected_revision=1,
                values={"title": f"edit {index}"},
            )

    results = await asyncio.gather(*(edit(index) for index in range(10)))

    assert len([result for result in results if result is not None]) == 1

    async with session_scope(live_app.state.session_factory) as session:
        final = await trips.get_owned(session, owner_id=owner_id, trip_id=trip_id)
    assert final is not None
    assert final.revision == 2


async def test_a_delete_racing_an_update_does_not_resurrect_the_trip(
    live_app: FastAPI, owner_id: uuid.UUID
) -> None:
    """`bump` excludes soft-deleted rows, so an in-flight edit cannot undo a deletion."""
    async with session_scope(live_app.state.session_factory) as session:
        created = await trips.create(session, owner_id=owner_id, values=trip_values())
        trip_id = created.id

    async with session_scope(live_app.state.session_factory) as session:
        await trips.soft_delete(session, owner_id=owner_id, trip_id=trip_id)

    async with session_scope(live_app.state.session_factory) as session:
        late = await trips.bump(
            session,
            owner_id=owner_id,
            trip_id=trip_id,
            expected_revision=1,
            values={"title": "still editing"},
        )

    assert late is None

    async with session_scope(live_app.state.session_factory) as session:
        row = await trips.get_owned(
            session, owner_id=owner_id, trip_id=trip_id, include_deleted=True
        )
    assert row is not None
    assert row.deleted_at is not None


async def test_two_concurrent_claims_of_one_key_produce_one_trip(
    live_app: FastAPI, owner_id: uuid.UUID
) -> None:
    """A client whose first attempt timed out and whose retry overlaps the original.

    Both pass the lookup, both try to insert; the unique constraint decides, and the loser must
    roll back its own trip as well as its claim rather than leaving an orphan behind.
    """
    key = f"race-{uuid.uuid4()}"
    payload = {"title": "Concurrency"}

    async def attempt() -> uuid.UUID | None:
        async with session_scope(live_app.state.session_factory) as session:
            try:
                async with session.begin_nested():
                    created = await trips.create(
                        session, owner_id=owner_id, values=trip_values()
                    )
                    await idempotency.record(
                        session,
                        owner_id=owner_id,
                        key=key,
                        operation="createTrip",
                        payload=payload,
                        resource_id=created.id,
                    )
                    return created.id
            except Exception:
                return None

    results = await asyncio.gather(attempt(), attempt())

    assert len([result for result in results if result is not None]) == 1

    async with session_scope(live_app.state.session_factory) as session:
        remaining = await session.scalar(
            text("SELECT count(*) FROM travel.trips WHERE user_id = :uid").bindparams(
                uid=owner_id
            )
        )
    assert remaining == 1, "the losing attempt left an orphan trip behind"
