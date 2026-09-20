"""Reading and writing `identity.consents`.

Append-only, and owner-scoped like everything else in this package. Recording a decision never
updates the previous one in place: the standing record is marked revoked and a new row is inserted,
so the table can answer what someone agreed to and when — which is the point of recording consent
rather than keeping a boolean on the profile.

"Effective" means all three of: granted, not revoked, and not expired. Checking only `granted`
would let a location grant work forever after it lapsed, which is the difference between a
one-off share and tracking.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import Consent

#: The contract's `ConsentType`, repeated here because the database column is a plain string. The
#: test suite asserts this matches the enum in `packages/contracts`.
CONSENT_TYPES: frozenset[str] = frozenset(
    {
        "LOCATION_ONCE",
        "LOCATION_LIVE",
        "ALERT_NOTIFICATION",
        "ANALYTICS",
        "EMERGENCY_PROFILE",
    }
)

#: Types that must not be granted open-endedly. A location grant with no expiry is tracking.
TYPES_REQUIRING_EXPIRY: frozenset[str] = frozenset({"LOCATION_ONCE", "LOCATION_LIVE"})


def cap_expiry(
    consent_type: str,
    requested: datetime | None,
    *,
    now: datetime,
    location_once_ttl_seconds: int,
    location_live_max_ttl_seconds: int,
) -> datetime | None:
    """The expiry the server will actually store.

    A client may ask for less and never for more. `LOCATION_ONCE` gets a fixed short life whatever
    it asked for — it exists for a single errand — and `LOCATION_LIVE` is clamped to the configured
    ceiling. Anything else keeps what was requested, including nothing.
    """
    if consent_type == "LOCATION_ONCE":
        ceiling = now + timedelta(seconds=location_once_ttl_seconds)
        return min(requested, ceiling) if requested else ceiling

    if consent_type == "LOCATION_LIVE":
        ceiling = now + timedelta(seconds=location_live_max_ttl_seconds)
        return min(requested, ceiling) if requested else ceiling

    return requested


def is_effective(consent: Consent, *, now: datetime) -> bool:
    """Granted, not revoked, not expired. All three, every time."""
    if not consent.granted or consent.revoked_at is not None:
        return False
    return consent.expires_at is None or consent.expires_at > now


async def record(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    consent_type: str,
    granted: bool,
    policy_version: str,
    expires_at: datetime | None,
) -> Consent:
    """Append a decision, superseding whatever stood before it for this type."""
    now = datetime.now(UTC)

    # Revoke first so there is never a moment with two standing records of the same type. Both rows
    # survive: the old one shows what was agreed and when it ended.
    await session.execute(
        update(Consent)
        .where(
            Consent.user_id == owner_id,
            Consent.type == consent_type,
            Consent.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    consent = Consent(
        user_id=owner_id,
        type=consent_type,
        granted=granted,
        policy_version=policy_version,
        granted_at=now,
        expires_at=expires_at if granted else None,
    )
    session.add(consent)
    await session.flush()
    return consent


async def list_standing(session: AsyncSession, *, owner_id: uuid.UUID) -> list[Consent]:
    """The current record for every type this person has ever acted on.

    Expired records are included rather than hidden: the UI has to be able to show that a grant
    lapsed, which is different from never having been asked.
    """
    result = await session.scalars(
        select(Consent)
        .where(Consent.user_id == owner_id, Consent.revoked_at.is_(None))
        .order_by(Consent.type)
    )
    return list(result)


async def get_effective(
    session: AsyncSession, *, owner_id: uuid.UUID, consent_type: str
) -> Consent | None:
    """The standing grant for one type, or None if there is nothing usable."""
    now = datetime.now(UTC)
    consent = await session.scalar(
        select(Consent).where(
            Consent.user_id == owner_id,
            Consent.type == consent_type,
            Consent.revoked_at.is_(None),
        )
    )
    if consent is None or not is_effective(consent, now=now):
        return None
    return consent


async def revoke_all(session: AsyncSession, *, owner_id: uuid.UUID) -> int:
    """Withdraw every standing consent, for account deletion.

    Returns how many were withdrawn so the deletion job can record it.
    """
    result = await session.execute(
        update(Consent)
        .where(Consent.user_id == owner_id, Consent.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return int(cast("CursorResult[Any]", result).rowcount or 0)
