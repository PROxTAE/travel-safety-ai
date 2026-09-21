"""Reading and writing `identity.emergency_profiles`.

This module is the only place a profile is sealed or opened, and it never accepts or returns a
plaintext payload without an owner id — that id is bound into the ciphertext, so a row cannot be
read as anyone but the person it belongs to.

There is no "get by id" and no listing. The only way to reach a row is to already know whose it is.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import EmergencyProfile
from app.security.envelope import EnvelopeCipher, SealedPayload


def _to_sealed(row: EmergencyProfile) -> SealedPayload:
    return SealedPayload(
        ciphertext=row.ciphertext,
        nonce=row.nonce,
        wrapped_key=row.wrapped_key,
        wrapped_key_nonce=row.wrapped_key_nonce,
        key_version=row.key_version,
    )


async def get_row(session: AsyncSession, *, owner_id: uuid.UUID) -> EmergencyProfile | None:
    """The sealed row, without opening it.

    Used by the deletion job and by anything that needs to know a profile exists — `/me` reports
    `has_emergency_profile` without decrypting, so the common request never touches the key.
    """
    row: EmergencyProfile | None = await session.scalar(
        select(EmergencyProfile).where(EmergencyProfile.user_id == owner_id)
    )
    return row


async def read(
    session: AsyncSession, *, owner_id: uuid.UUID, cipher: EnvelopeCipher
) -> tuple[dict[str, Any], EmergencyProfile] | None:
    """Open the caller's profile, or None if they have none."""
    row = await get_row(session, owner_id=owner_id)
    if row is None:
        return None
    return cipher.open(_to_sealed(row), owner_id=owner_id), row


async def upsert(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    payload: dict[str, Any],
    cipher: EnvelopeCipher,
) -> EmergencyProfile:
    """Replace the caller's profile.

    A replace rather than a merge, and one row per user, so an earlier version of someone's medical
    details is never left behind in the table.
    """
    sealed = cipher.seal(payload, owner_id=owner_id)
    row = await get_row(session, owner_id=owner_id)

    if row is None:
        row = EmergencyProfile(user_id=owner_id)
        session.add(row)

    row.ciphertext = sealed.ciphertext
    row.nonce = sealed.nonce
    row.wrapped_key = sealed.wrapped_key
    row.wrapped_key_nonce = sealed.wrapped_key_nonce
    row.key_version = sealed.key_version

    await session.flush()
    # `updated_at` has a server-side `onupdate`, so the flush leaves it expired. Reading it in the
    # handler would then trigger a lazy load from async code, which raises MissingGreenlet rather
    # than quietly fetching — refresh it here, where there is an await to do it in.
    await session.refresh(row, attribute_names=["created_at", "updated_at"])
    return row


async def purge(session: AsyncSession, *, owner_id: uuid.UUID) -> bool:
    """Delete the row outright.

    A hard delete, not a soft one. Everywhere else in this service deletion is soft so the record
    survives for audit, but there is nothing to audit here that is worth keeping: the row is
    somebody's medical details, and the audit log already records that a profile existed and was
    removed.
    """
    result = await session.execute(
        delete(EmergencyProfile).where(EmergencyProfile.user_id == owner_id)
    )
    return bool(cast("CursorResult[Any]", result).rowcount)


async def rewrap(session: AsyncSession, *, owner_id: uuid.UUID, cipher: EnvelopeCipher) -> bool:
    """Move one row onto the active key without decrypting the payload.

    What makes key rotation affordable: only the wrapped data key changes, so rotating a large
    table is a small update per row rather than a full rewrite.
    """
    row = await get_row(session, owner_id=owner_id)
    if row is None or row.key_version == cipher.active_version:
        return False

    sealed = cipher.rewrap(_to_sealed(row), owner_id=owner_id)
    row.wrapped_key = sealed.wrapped_key
    row.wrapped_key_nonce = sealed.wrapped_key_nonce
    row.key_version = sealed.key_version
    await session.flush()
    return True
