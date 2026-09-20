"""Making a retried mutation safe.

The contract promises that a retry with the same `Idempotency-Key` returns the original result, and
that the same key with a different payload is refused. Without that, a request that timed out on
the network — which is indistinguishable from one that failed — leaves the client with no safe
move: retrying risks a duplicate trip, and not retrying loses the one it made.

Neither the key nor the body is stored. Both are reduced to a SHA-256 digest: the key is a bearer
value a client may reuse elsewhere, and the body carries the coordinates of somebody's journey.
Comparing digests answers the only two questions this table has to answer.

The two functions are split rather than combined because the resource does not exist yet when the
key is first examined. `lookup` runs before the work and answers "has this already been done";
`record` runs after it, inside the same savepoint as the creation, so a key and the row it names
are committed together or not at all.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.travel import IdempotencyKey

#: How long a key is remembered. Long enough to cover any retry a client or a proxy would make,
#: short enough that a key is not held for ever.
DEFAULT_TTL = timedelta(hours=24)


class KeyConflict(Exception):
    """The key was used before, for a different payload."""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_digest(payload: Any) -> str:
    """A stable digest of a request body.

    `sort_keys` so two JSON objects differing only in key order are recognised as the same request —
    which they are. Treating them as a conflict would reject a good retry from a client that
    serialises its dict in a different order the second time.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return digest(canonical)


async def lookup(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    key: str,
    operation: str,
    payload: Any,
    now: datetime | None = None,
) -> uuid.UUID | None:
    """What this key already refers to, or None if it is free.

    Raises `KeyConflict` when the key is live but was used for a different payload or a different
    operation — the case where returning the earlier resource would be answering a question the
    client did not ask.
    """
    moment = now or datetime.now(UTC)

    existing = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == owner_id,
            IdempotencyKey.key_digest == digest(key),
        )
    )
    if existing is None:
        return None

    if existing.expires_at <= moment:
        # Past its window: the key is free again, and the stale row is replaced by `record`.
        return None

    if existing.operation != operation or existing.request_digest != request_digest(payload):
        raise KeyConflict

    return existing.resource_id


async def record(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    key: str,
    operation: str,
    payload: Any,
    resource_id: uuid.UUID,
    ttl: timedelta = DEFAULT_TTL,
) -> None:
    """Bind the key to the resource that was just created.

    Called inside the same savepoint as the creation. A plain INSERT, so two concurrent retries
    race on the unique constraint and exactly one wins; the loser's `IntegrityError` is what tells
    the handler to roll back its own creation and return the winner's.
    """
    now = datetime.now(UTC)

    # An expired row for the same key still occupies the unique slot, so clear it first rather than
    # letting the insert collide with something that is no longer in force.
    await session.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.user_id == owner_id,
            IdempotencyKey.key_digest == digest(key),
            IdempotencyKey.expires_at <= now,
        )
    )

    session.add(
        IdempotencyKey(
            user_id=owner_id,
            key_digest=digest(key),
            request_digest=request_digest(payload),
            operation=operation,
            resource_id=resource_id,
            expires_at=now + ttl,
        )
    )
    await session.flush()


async def purge_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Remove keys past their window. Run by the retention job."""
    cutoff = now or datetime.now(UTC)
    result = await session.execute(
        delete(IdempotencyKey).where(IdempotencyKey.expires_at <= cutoff)
    )
    return int(cast("CursorResult[Any]", result).rowcount or 0)
