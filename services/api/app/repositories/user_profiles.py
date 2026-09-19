"""Reading and writing `identity.user_profiles`.

Every query here takes the owner explicitly and filters on it. That is not politeness — it is the
rule from §"User identity" of the module plan: ownership is enforced *at the repository query*,
not in the handler. A handler can forget a check; a repository that has no method capable of
returning someone else's row cannot be asked to.

There is deliberately no `get_by_id(user_id)` without an owner. If phase 4 needs an admin read, it
gets its own clearly-named method with its own authorisation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import UserProfile


async def get_or_create_by_subject(
    session: AsyncSession,
    *,
    subject_id: str,
    default_locale: str,
    default_timezone: str,
) -> UserProfile:
    """Resolve an OIDC subject to its internal profile, creating it on first sight.

    `ON CONFLICT DO NOTHING` followed by a read handles the race where two requests from a
    brand-new user arrive together — which is the normal case, because a freshly signed-in browser
    fires several requests at once. Catching the unique violation afterwards would work too, but
    only after poisoning the transaction.
    """
    existing = await session.scalar(select(UserProfile).where(UserProfile.subject_id == subject_id))
    if existing is not None:
        return existing

    await session.execute(
        pg_insert(UserProfile)
        .values(
            subject_id=subject_id,
            locale=default_locale,
            timezone=default_timezone,
        )
        .on_conflict_do_nothing(index_elements=[UserProfile.subject_id])
    )

    created = await session.scalar(select(UserProfile).where(UserProfile.subject_id == subject_id))
    if created is None:  # pragma: no cover - only reachable if the row vanished mid-transaction
        raise RuntimeError("the profile could not be created or read back")
    return created


async def get_owned(session: AsyncSession, *, owner_id: uuid.UUID) -> UserProfile | None:
    """The caller's own profile, or None.

    A soft-deleted profile is not returned. The row stays for the retention job, but as far as the
    API is concerned the account is gone.
    """
    profile: UserProfile | None = await session.scalar(
        select(UserProfile).where(
            UserProfile.id == owner_id,
            UserProfile.deleted_at.is_(None),
        )
    )
    return profile


async def touch(session: AsyncSession, *, owner_id: uuid.UUID) -> None:
    """Record that the profile was used, without loading it."""
    await session.execute(
        update(UserProfile).where(UserProfile.id == owner_id).values(updated_at=datetime.now(UTC))
    )
