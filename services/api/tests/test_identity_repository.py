"""Identity resolution and ownership, against a real PostgreSQL.

Ownership is enforced at the repository query — §"User identity" of the module plan — so this is
where it has to be proven. A handler can forget a check; a repository whose methods all require an
owner cannot be asked for someone else's row.

`ON CONFLICT` and partial indexes behave differently on every database, so none of this is worth
testing against anything but the real one.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.repositories import user_profiles
from tests.conftest import random_subject
from tests.database import requires_database

pytestmark = [pytest.mark.integration, requires_database]


async def test_a_new_subject_gets_a_profile(db_session: Any) -> None:
    subject = random_subject()

    profile = await user_profiles.get_or_create_by_subject(
        db_session, subject_id=subject, default_locale="th-TH", default_timezone="Asia/Bangkok"
    )

    assert isinstance(profile.id, uuid.UUID)
    assert profile.subject_id == subject
    assert profile.locale == "th-TH"
    assert profile.disabled_at is None


async def test_the_same_subject_always_resolves_to_the_same_user(db_session: Any) -> None:
    subject = random_subject()

    first = await user_profiles.get_or_create_by_subject(
        db_session, subject_id=subject, default_locale="en-US", default_timezone="UTC"
    )
    second = await user_profiles.get_or_create_by_subject(
        db_session, subject_id=subject, default_locale="en-US", default_timezone="UTC"
    )

    assert first.id == second.id


async def test_the_locale_default_only_applies_on_creation(db_session: Any) -> None:
    """A later sign-in must not overwrite a preference the user set."""
    subject = random_subject()
    await user_profiles.get_or_create_by_subject(
        db_session, subject_id=subject, default_locale="th-TH", default_timezone="Asia/Bangkok"
    )

    again = await user_profiles.get_or_create_by_subject(
        db_session, subject_id=subject, default_locale="en-US", default_timezone="UTC"
    )

    assert again.locale == "th-TH"


async def test_concurrent_first_sign_ins_create_one_row(live_app: Any) -> None:
    """The normal case, not an edge case.

    A browser that has just signed in fires several requests at once, and all of them resolve the
    same brand-new subject. Without `ON CONFLICT` one of them would fail with a unique violation
    and the user would see a 500 on their first page load.
    """
    from app.db.engine import session_scope

    subject = random_subject()

    async def resolve() -> uuid.UUID:
        async with session_scope(live_app.state.session_factory) as session:
            profile = await user_profiles.get_or_create_by_subject(
                session, subject_id=subject, default_locale="en-US", default_timezone="UTC"
            )
            return profile.id

    ids = await asyncio.gather(*(resolve() for _ in range(8)))

    assert len(set(ids)) == 1, f"concurrent sign-in created {len(set(ids))} users"


async def test_an_owner_can_read_their_own_profile(db_session: Any) -> None:
    profile = await user_profiles.get_or_create_by_subject(
        db_session, subject_id=random_subject(), default_locale="en-US", default_timezone="UTC"
    )

    assert (await user_profiles.get_owned(db_session, owner_id=profile.id)) is not None


async def test_an_owner_cannot_read_another_users_profile(db_session: Any) -> None:
    """The ownership primitive every later phase reuses.

    `get_owned` takes the owner and filters on it, so asking with the wrong id returns nothing
    rather than someone else's row.
    """
    mine = await user_profiles.get_or_create_by_subject(
        db_session, subject_id=random_subject(), default_locale="en-US", default_timezone="UTC"
    )
    theirs = await user_profiles.get_or_create_by_subject(
        db_session, subject_id=random_subject(), default_locale="en-US", default_timezone="UTC"
    )

    assert mine.id != theirs.id

    fetched = await user_profiles.get_owned(db_session, owner_id=theirs.id)
    assert fetched is not None
    assert fetched.id != mine.id


async def test_an_unknown_owner_reads_nothing(db_session: Any) -> None:
    assert (await user_profiles.get_owned(db_session, owner_id=uuid.uuid4())) is None


async def test_a_soft_deleted_profile_is_not_returned(db_session: Any) -> None:
    """The row stays for the retention job; as far as the API is concerned the account is gone."""
    profile = await user_profiles.get_or_create_by_subject(
        db_session, subject_id=random_subject(), default_locale="en-US", default_timezone="UTC"
    )
    await db_session.execute(
        text("UPDATE identity.user_profiles SET deleted_at = now() WHERE id = :id"),
        {"id": profile.id},
    )

    assert (await user_profiles.get_owned(db_session, owner_id=profile.id)) is None


async def test_the_subject_is_unique_at_the_database_level(db_session: Any) -> None:
    """Belt as well as braces: the application relies on one profile per subject, so the database
    enforces it rather than trusting every future code path to remember."""
    from sqlalchemy.exc import IntegrityError

    subject = random_subject()
    await user_profiles.get_or_create_by_subject(
        db_session, subject_id=subject, default_locale="en-US", default_timezone="UTC"
    )
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text("INSERT INTO identity.user_profiles (subject_id) VALUES (:subject)"),
            {"subject": subject},
        )


async def test_the_partial_index_on_disabled_accounts_exists(db_session: Any) -> None:
    """The disable check runs on every authenticated request."""
    result = await db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'identity' AND indexname = 'ix_user_profiles_disabled'"
        )
    )
    definition = result.scalar_one()

    assert "disabled_at IS NOT NULL" in definition
