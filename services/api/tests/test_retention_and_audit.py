"""The export and deletion worker, the audit trail, and persistence across a restart.

Three things Phase 3 has to prove and only a real database can show: that data survives the process
that wrote it, that a deletion actually removes what this service owns while being honest about
what it cannot reach, and that the audit log records actions without recording their content.
"""

from __future__ import annotations

import io
import json
import uuid
from contextlib import redirect_stdout
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.cli.retention import process_one
from app.db.engine import session_scope
from app.db.models.identity import DataSubjectRequest
from app.repositories import audit, data_subject_requests
from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]

POLICY = "1.0.0"
PROFILE = {
    "blood_type": "A+",
    "allergies": ["shellfish"],
    "medical_notes": "Wears a medical alert bracelet.",
    "contacts": [{"name": "Kanya Wong", "phone": "+66899999999"}],
}


@pytest.fixture(scope="module")
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture
def authed_app(live_app: FastAPI, key: SigningKeyPair) -> FastAPI:
    live_app.state.jwks = StubJwks.containing(key)
    return live_app


@pytest.fixture
async def authed_client(authed_app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=authed_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def a_user_with_everything(
    client: httpx.AsyncClient, key: SigningKeyPair
) -> tuple[str, uuid.UUID]:
    """A signed-in person with a profile, a consent and an emergency profile."""
    token = key.sign({"sub": f"retention-{uuid.uuid4()}"})
    me = await client.get("/api/v1/me", headers=auth(token))
    user_id = uuid.UUID(me.json()["data"]["user_id"])

    await client.patch("/api/v1/me", headers=auth(token), json={"timezone": "Asia/Bangkok"})
    await client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": "EMERGENCY_PROFILE", "granted": True, "policy_version": POLICY},
    )
    stored = await client.put("/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE)
    assert stored.status_code == 200, stored.text
    return token, user_id


# --- persistence ----------------------------------------------------------------------------------


async def test_data_survives_the_process_that_wrote_it(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, live_settings: Any
) -> None:
    """The phase 3 exit criterion.

    A second application instance — new engine, new connection pool, nothing shared but the
    database — reads back what the first one wrote. That is what "restart the container and the
    data is still there" means, without the minutes a real restart would cost.
    """
    token, _ = await a_user_with_everything(authed_client, key)

    from app.main import create_app

    second = create_app(live_settings)
    async with second.router.lifespan_context(second):
        second.state.jwks = StubJwks.containing(key)
        transport = httpx.ASGITransport(app=second, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            profile = await client.get("/api/v1/me", headers=auth(token))
            emergency = await client.get("/api/v1/me/emergency-profile", headers=auth(token))

    assert profile.json()["data"]["timezone"] == "Asia/Bangkok"
    assert emergency.status_code == 200
    assert emergency.json()["data"]["medical_notes"] == PROFILE["medical_notes"]


# --- export ---------------------------------------------------------------------------------------


async def test_an_export_gathers_what_this_service_holds(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, live_app: FastAPI, live_settings: Any
) -> None:
    _, user_id = await a_user_with_everything(authed_client, key)

    async with session_scope(live_app.state.session_factory) as session:
        await data_subject_requests.enqueue(
            session, owner_id=user_id, kind=data_subject_requests.KIND_EXPORT
        )

    captured = io.StringIO()
    async with session_scope(live_app.state.session_factory) as session:
        with redirect_stdout(captured):
            kind = await process_one(session, live_settings)

    assert kind == data_subject_requests.KIND_EXPORT
    document = json.loads(captured.getvalue().strip().splitlines()[-1])

    assert document["profile"]["timezone"] == "Asia/Bangkok"
    assert any(item["type"] == "EMERGENCY_PROFILE" for item in document["consents"])
    assert document["emergency_profile"]["contents"]["medical_notes"] == PROFILE["medical_notes"]


async def test_an_export_withholds_data_whose_consent_was_withdrawn(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, live_app: FastAPI, live_settings: Any
) -> None:
    """An export must not become the way to read data whose consent no longer stands."""
    token, user_id = await a_user_with_everything(authed_client, key)
    await authed_client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": "EMERGENCY_PROFILE", "granted": False, "policy_version": POLICY},
    )

    async with session_scope(live_app.state.session_factory) as session:
        await data_subject_requests.enqueue(
            session, owner_id=user_id, kind=data_subject_requests.KIND_EXPORT
        )

    captured = io.StringIO()
    async with session_scope(live_app.state.session_factory) as session:
        with redirect_stdout(captured):
            await process_one(session, live_settings)

    document = json.loads(captured.getvalue().strip().splitlines()[-1])
    assert document["emergency_profile"]["present"] is True
    assert document["emergency_profile"]["contents_withheld_because"] == "consent_withdrawn"
    assert PROFILE["medical_notes"] not in captured.getvalue()


# --- deletion -------------------------------------------------------------------------------------


async def test_a_deletion_removes_what_this_service_owns(
    authed_client: httpx.AsyncClient,
    key: SigningKeyPair,
    live_app: FastAPI,
    live_settings: Any,
    db_session: Any,
) -> None:
    token, user_id = await a_user_with_everything(authed_client, key)

    async with session_scope(live_app.state.session_factory) as session:
        await data_subject_requests.enqueue(
            session, owner_id=user_id, kind=data_subject_requests.KIND_DELETE
        )
    async with session_scope(live_app.state.session_factory) as session:
        await process_one(session, live_settings)

    remaining = (
        await db_session.execute(
            text("SELECT count(*) FROM identity.emergency_profiles WHERE user_id = :id"),
            {"id": user_id},
        )
    ).scalar_one()
    standing = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM identity.consents "
                "WHERE user_id = :id AND revoked_at IS NULL"
            ),
            {"id": user_id},
        )
    ).scalar_one()
    deleted_at = (
        await db_session.execute(
            text("SELECT deleted_at FROM identity.user_profiles WHERE id = :id"), {"id": user_id}
        )
    ).scalar_one()

    assert remaining == 0, "the emergency profile survived deletion"
    assert standing == 0, "a consent still stands after deletion"
    assert deleted_at is not None

    # And the account stops working immediately, not at the next token expiry.
    assert (await authed_client.get("/api/v1/me", headers=auth(token))).status_code == 401


async def test_a_completed_deletion_says_what_it_could_not_reach(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, live_app: FastAPI, live_settings: Any
) -> None:
    """The honesty requirement. COMPLETED here means "everything this service owns", and the other
    five schemas belong to services that do not exist yet."""
    _, user_id = await a_user_with_everything(authed_client, key)

    async with session_scope(live_app.state.session_factory) as session:
        request = await data_subject_requests.enqueue(
            session, owner_id=user_id, kind=data_subject_requests.KIND_DELETE
        )
        request_id = request.id
    async with session_scope(live_app.state.session_factory) as session:
        await process_one(session, live_settings)

    async with session_scope(live_app.state.session_factory) as session:
        finished = await session.get(DataSubjectRequest, request_id)
        assert finished is not None
        assert finished.status == data_subject_requests.STATUS_COMPLETED
        assert set(finished.incomplete_scopes) == set(data_subject_requests.UNREACHABLE_SCOPES)
        assert finished.completed_at is not None


async def test_asking_twice_does_not_queue_the_work_twice(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, live_app: FastAPI
) -> None:
    """Someone who clicks delete twice because nothing visibly happened should not get two jobs."""
    _, user_id = await a_user_with_everything(authed_client, key)

    async with session_scope(live_app.state.session_factory) as session:
        first = await data_subject_requests.enqueue(
            session, owner_id=user_id, kind=data_subject_requests.KIND_DELETE
        )
        second = await data_subject_requests.enqueue(
            session, owner_id=user_id, kind=data_subject_requests.KIND_DELETE
        )

        assert first.id == second.id


async def test_an_empty_queue_is_not_an_error(live_app: FastAPI, live_settings: Any) -> None:
    async with session_scope(live_app.state.session_factory) as session:
        # Drain whatever earlier tests left, then confirm the next call reports nothing to do.
        while await process_one(session, live_settings) is not None:
            pass
        assert await process_one(session, live_settings) is None


# --- the audit trail ------------------------------------------------------------------------------


async def test_every_action_is_recorded(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, db_session: Any
) -> None:
    _, user_id = await a_user_with_everything(authed_client, key)

    actions = {
        row[0]
        for row in await db_session.execute(
            text("SELECT action FROM identity.audit_log WHERE user_id = :id"), {"id": user_id}
        )
    }

    assert {
        audit.ACTION_PROFILE_UPDATED,
        audit.ACTION_CONSENT_RECORDED,
        audit.ACTION_EMERGENCY_PROFILE_WRITTEN,
    } <= actions


async def test_the_audit_entry_carries_the_request_id(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, db_session: Any
) -> None:
    """So an entry can be matched to the log lines for the same request."""
    _, user_id = await a_user_with_everything(authed_client, key)

    request_ids = [
        row[0]
        for row in await db_session.execute(
            text("SELECT request_id FROM identity.audit_log WHERE user_id = :id"), {"id": user_id}
        )
    ]

    assert request_ids and all(value is not None for value in request_ids)


async def test_no_audit_entry_anywhere_contains_profile_content(db_session: Any) -> None:
    """Swept across the whole table, not just the rows this test wrote: an audit log that quotes
    the data it audits is a second, less guarded copy of it."""
    blob = "".join(
        row[0]
        for row in await db_session.execute(text("SELECT details::text FROM identity.audit_log"))
    )

    for secret in ("shellfish", "medical alert", "Kanya", "66899999999", "penicillin", "Somchai"):
        assert secret not in blob, f"{secret!r} reached the audit log"


def test_the_audit_helper_refuses_content_outright() -> None:
    """A check rather than a convention, because forgetting is easy and the cost is high."""
    from app.repositories.audit import AuditDetailRejected, _check_details

    _check_details({"allergy_count": 2, "key_version": "v1"})

    with pytest.raises(AuditDetailRejected):
        _check_details({"allergies": "penicillin"})
    with pytest.raises(AuditDetailRejected):
        _check_details({"medical_notes": "anything"})
    with pytest.raises(AuditDetailRejected):
        _check_details({"summary": {"nested": "content"}})


async def test_an_audit_entry_outlives_the_account_it_describes(
    authed_client: httpx.AsyncClient,
    key: SigningKeyPair,
    live_app: FastAPI,
    live_settings: Any,
    db_session: Any,
) -> None:
    """That an account was deleted is worth keeping. Who it was is not."""
    _, user_id = await a_user_with_everything(authed_client, key)

    async with session_scope(live_app.state.session_factory) as session:
        await data_subject_requests.enqueue(
            session, owner_id=user_id, kind=data_subject_requests.KIND_DELETE
        )
    async with session_scope(live_app.state.session_factory) as session:
        await process_one(session, live_settings)

    entries = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM identity.audit_log "
                "WHERE user_id = :id AND action = 'ACCOUNT_DELETED'"
            ),
            {"id": user_id},
        )
    ).scalar_one()

    assert entries == 1
