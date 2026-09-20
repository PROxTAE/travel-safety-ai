"""Reading and writing `travel.trips`.

Every function takes `owner_id` and filters on it. There is no `get(trip_id)` that omits it, so
"read someone else's trip" is not an operation this module can express — which is a stronger
guarantee than remembering an ownership check in each of five handlers.

The interesting function is `bump`. Optimistic concurrency is implemented as a conditional UPDATE
rather than read-then-write: the revision the client claims is part of the WHERE clause, so two
requests racing on the same trip are resolved by PostgreSQL rather than by whichever handler
happened to read first.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.travel import Trip

#: Columns a caller may never set directly, whatever the request body says. Listed here as well as
#: being absent from `UpdateTripRequest`, because this is the layer that would actually write them.
SERVER_OWNED_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "user_id",
        "revision",
        "selected_route_id",
        "previous_selected_route_id",
        "latest_request_id",
        "created_at",
        "updated_at",
        "deleted_at",
    }
)


def _owned(owner_id: uuid.UUID, *, include_deleted: bool = False) -> Select[tuple[Trip]]:
    """The only starting point for a query in this module."""
    statement = select(Trip).where(Trip.user_id == owner_id)
    if not include_deleted:
        statement = statement.where(Trip.deleted_at.is_(None))
    return statement


async def get_owned(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    trip_id: uuid.UUID,
    include_deleted: bool = False,
) -> Trip | None:
    """One trip belonging to this caller, or None.

    None covers both "no such trip" and "somebody else's trip" on purpose. The handler turns it
    into 404 either way: answering 403 for the second would confirm the id exists, which is all an
    attacker needs to enumerate other people's trips.
    """
    trip: Trip | None = await session.scalar(
        _owned(owner_id, include_deleted=include_deleted).where(Trip.id == trip_id)
    )
    return trip


async def list_owned(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    limit: int,
    cursor: tuple[datetime, uuid.UUID] | None = None,
    status: str | None = None,
) -> tuple[list[Trip], bool]:
    """A page of the caller's trips, newest departure first.

    Keyset pagination rather than OFFSET: a trip created while someone is paging would shift every
    later page by one and hide a row. The key is `(departure_time, id)` — the id breaks ties
    between two trips leaving at the same moment, which is common enough that ordering by the
    timestamp alone would make the cursor ambiguous.

    Returns the page and whether more rows follow, established by asking for one extra row rather
    than by running a second COUNT over the whole table.
    """
    statement = _owned(owner_id, include_deleted=status == "DELETED")

    if status is not None:
        statement = statement.where(Trip.status == status)

    if cursor is not None:
        # Strictly after the cursor in the same DESC order the rows are returned in.
        statement = statement.where(tuple_(Trip.departure_time, Trip.id) < cursor)

    statement = statement.order_by(Trip.departure_time.desc(), Trip.id.desc()).limit(limit + 1)

    rows = list((await session.scalars(statement)).all())
    has_more = len(rows) > limit
    return rows[:limit], has_more


async def create(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    values: dict[str, Any],
) -> Trip:
    """Insert a trip at revision 1."""
    forbidden = SERVER_OWNED_FIELDS & set(values)
    if forbidden:  # pragma: no cover - the request model forbids these fields already
        raise ValueError(f"caller may not set {sorted(forbidden)}")

    trip = Trip(user_id=owner_id, revision=1, **values)
    session.add(trip)
    await session.flush()
    # Server defaults (id, timestamps, status) are not on the instance until it is read back, and
    # reading an expired attribute inside an async handler would trigger lazy IO outside the
    # greenlet that owns the connection.
    await session.refresh(trip)
    return trip


async def bump(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    trip_id: uuid.UUID,
    expected_revision: int,
    values: dict[str, Any],
    server_values: dict[str, Any] | None = None,
) -> Trip | None:
    """Apply changes if the trip is still at `expected_revision`, and increment it.

    `values` is what the caller asked for and is checked against `SERVER_OWNED_FIELDS`.
    `server_values` is what this service decided on its own — currently only the clearing of an
    assessment that no longer describes the journey — and is not, because the guard exists to stop
    a request body reaching these columns, not to stop the service writing them.

    Returns None when nothing matched, which means one of three things: no such trip, not this
    caller's trip, or the revision has moved. The handler separates the last case from the first
    two by re-reading; it cannot be distinguished here, and conflating them in the response is the
    behaviour that stops trip ids being probed.

    A single statement, so the check and the write cannot be interleaved with another request's.
    """
    forbidden = SERVER_OWNED_FIELDS & set(values)
    if forbidden:  # pragma: no cover - guarded at the schema layer too
        raise ValueError(f"caller may not set {sorted(forbidden)}")

    statement = (
        update(Trip)
        .where(
            Trip.id == trip_id,
            Trip.user_id == owner_id,
            Trip.deleted_at.is_(None),
            Trip.revision == expected_revision,
        )
        .values(
            revision=Trip.revision + 1,
            updated_at=datetime.now(UTC),
            **values,
            **(server_values or {}),
        )
        .returning(Trip)
    )

    updated = (await session.execute(statement)).scalar_one_or_none()
    if updated is not None:
        # RETURNING gives the new row, but the identity map may still hold the pre-update instance.
        await session.refresh(updated)
    return updated


async def clear_assessment(
    session: AsyncSession, *, owner_id: uuid.UUID, trip_id: uuid.UUID
) -> None:
    """Detach the trip from an assessment that no longer describes it.

    Called when a change touches the journey itself. The alternative — leaving the pointer in
    place — would let the UI keep showing a verdict reached for a different route or a different
    departure time, which is the single most dangerous stale value in this service.
    """
    await session.execute(
        update(Trip)
        .where(Trip.id == trip_id, Trip.user_id == owner_id)
        .values(latest_request_id=None, selected_route_id=None)
    )


async def soft_delete(
    session: AsyncSession, *, owner_id: uuid.UUID, trip_id: uuid.UUID
) -> Trip | None:
    """Mark the trip deleted. Returns None if there was nothing of the caller's to delete.

    The row stays for the retention window: an assessment already produced for this trip is
    referenced by other services, and removing the trip underneath them would leave records
    pointing at nothing. The purge is the retention job's work.
    """
    statement = (
        update(Trip)
        .where(Trip.id == trip_id, Trip.user_id == owner_id, Trip.deleted_at.is_(None))
        .values(
            deleted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            status="DELETED",
            revision=Trip.revision + 1,
        )
        .returning(Trip)
    )
    deleted = (await session.execute(statement)).scalar_one_or_none()
    if deleted is not None:
        await session.refresh(deleted)
    return deleted


async def count_owned(session: AsyncSession, *, owner_id: uuid.UUID) -> int:
    """How many live trips the caller has. Used by the export job, not by the API."""
    total = await session.scalar(
        select(func.count())
        .select_from(Trip)
        .where(Trip.user_id == owner_id, Trip.deleted_at.is_(None))
    )
    return int(total or 0)


# --- pagination cursors -------------------------------------------------------------------------
#
# Opaque to the client by contract. Not encrypted, because it carries nothing private — a departure
# time and a trip id the caller already has — but base64 so nobody builds one by hand and then
# depends on the format.


def encode_cursor(departure_time: datetime, trip_id: uuid.UUID) -> str:
    raw = f"{departure_time.astimezone(UTC).isoformat()}|{trip_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    """Parse a cursor, or None if it is not one.

    Returns None rather than raising for anything malformed. A bad cursor is a 400 with a field
    error, not a 500, and the handler is the layer that knows which it is.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        timestamp, _, identifier = raw.partition("|")
        if not timestamp or not identifier:
            return None
        return datetime.fromisoformat(timestamp), uuid.UUID(identifier)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def cursor_for(rows: Sequence[Trip]) -> str | None:
    """The cursor that resumes after the last row of a page."""
    if not rows:
        return None
    last = rows[-1]
    return encode_cursor(last.departure_time, last.id)


__all__ = [
    "SERVER_OWNED_FIELDS",
    "bump",
    "clear_assessment",
    "count_owned",
    "create",
    "cursor_for",
    "decode_cursor",
    "encode_cursor",
    "get_owned",
    "list_owned",
    "soft_delete",
]
