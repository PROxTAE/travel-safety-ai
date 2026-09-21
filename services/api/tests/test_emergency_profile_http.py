"""The emergency profile, over HTTP against a real database.

This is the most sensitive data the service holds, so the tests are less about the happy path than
about what happens around it: that nothing is stored in the clear, that consent gates it both ways,
that one person cannot read another's, that the database holds no readable copy, and that no field
reaches the logs.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from tests.conftest import build_settings
from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]

POLICY = "1.0.0"

PROFILE = {
    "blood_type": "O+",
    "allergies": ["penicillin", "peanuts"],
    "medical_notes": "Carries an adrenaline auto-injector in the left jacket pocket.",
    "medications": ["levothyroxine"],
    "contacts": [{"name": "Somchai Jaidee", "relationship": "spouse", "phone": "+66812345678"}],
    "insurance": {"provider_name": "Example Assurance", "policy_reference": "EX-123456"},
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


@pytest.fixture
def token(key: SigningKeyPair) -> str:
    return key.sign({"sub": f"emergency-{uuid.uuid4()}"})


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def with_consent(client: httpx.AsyncClient, token: str) -> None:
    response = await client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": "EMERGENCY_PROFILE", "granted": True, "policy_version": POLICY},
    )
    assert response.status_code == 201, response.text


# --- the round trip -------------------------------------------------------------------------------


async def test_a_profile_can_be_stored_and_read_back(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    await with_consent(authed_client, token)

    stored = await authed_client.put(
        "/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE
    )
    assert stored.status_code == 200, stored.text

    read = await authed_client.get("/api/v1/me/emergency-profile", headers=auth(token))
    assert read.status_code == 200

    data = read.json()["data"]
    assert data["blood_type"] == PROFILE["blood_type"]
    assert data["allergies"] == PROFILE["allergies"]
    assert data["medical_notes"] == PROFILE["medical_notes"]
    assert data["contacts"][0]["phone"] == PROFILE["contacts"][0]["phone"]
    assert data["key_version"]


async def test_a_replacement_leaves_no_older_copy(
    authed_client: httpx.AsyncClient, token: str, db_session: Any
) -> None:
    """One row per user. An earlier version of someone's medical details must not linger."""
    await with_consent(authed_client, token)
    await authed_client.put("/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE)
    await authed_client.put(
        "/api/v1/me/emergency-profile",
        headers=auth(token),
        json={**PROFILE, "medical_notes": "Updated."},
    )

    replaced = await authed_client.put(
        "/api/v1/me/emergency-profile",
        headers=auth(token),
        json={**PROFILE, "medical_notes": "Updated."},
    )
    assert replaced.status_code == 200, replaced.text

    read = await authed_client.get("/api/v1/me/emergency-profile", headers=auth(token))
    assert read.json()["data"]["medical_notes"] == "Updated."

    rows = (
        await db_session.execute(text("SELECT count(*) FROM identity.emergency_profiles"))
    ).scalar_one()
    profiles = (
        await db_session.execute(
            text("SELECT count(DISTINCT user_id) FROM identity.emergency_profiles")
        )
    ).scalar_one()
    assert rows == profiles, "more rows than users means an old copy was kept"


async def test_the_profile_flag_appears_on_me(authed_client: httpx.AsyncClient, token: str) -> None:
    await with_consent(authed_client, token)
    before = (await authed_client.get("/api/v1/me", headers=auth(token))).json()["data"]
    assert before["has_emergency_profile"] is False

    await authed_client.put("/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE)

    after = (await authed_client.get("/api/v1/me", headers=auth(token))).json()["data"]
    assert after["has_emergency_profile"] is True


async def test_an_empty_profile_is_valid(authed_client: httpx.AsyncClient, token: str) -> None:
    """Someone may want the record to exist with nothing in it yet."""
    await with_consent(authed_client, token)

    response = await authed_client.put("/api/v1/me/emergency-profile", headers=auth(token), json={})

    assert response.status_code == 200
    assert response.json()["data"]["allergies"] == []


# --- what the database actually holds -------------------------------------------------------------


async def test_the_database_holds_no_readable_copy(
    authed_client: httpx.AsyncClient, token: str, db_session: Any
) -> None:
    """The check that matters. A `SELECT *` during debugging must show bytes, not a medical note."""
    await with_consent(authed_client, token)
    await authed_client.put("/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE)

    dumped = (
        (
            await db_session.execute(
                text(
                    "SELECT encode(ciphertext, 'escape') || encode(wrapped_key, 'escape') "
                    "FROM identity.emergency_profiles"
                )
            )
        )
        .scalars()
        .all()
    )
    blob = "".join(dumped)

    for secret in ("penicillin", "peanuts", "adrenaline", "Somchai", "66812345678", "EX-123456"):
        assert secret not in blob, f"{secret!r} is readable in the database"


async def test_the_table_has_no_column_for_the_contents(db_session: Any) -> None:
    """There is deliberately no blood_type column: the searchable copy is the copy that leaks."""
    columns = {
        row[0]
        for row in await db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'identity' AND table_name = 'emergency_profiles'"
            )
        )
    }

    assert columns & {"blood_type", "allergies", "medical_notes", "contacts"} == set()


# --- consent gates it both ways -------------------------------------------------------------------


async def test_storing_without_consent_is_refused(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """Being signed in is not agreement to store medical data."""
    response = await authed_client.put(
        "/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_withdrawing_consent_takes_effect_immediately(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """Not at the next purge run. Withdrawal has to mean something the moment it is made."""
    await with_consent(authed_client, token)
    await authed_client.put("/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE)
    assert (
        await authed_client.get("/api/v1/me/emergency-profile", headers=auth(token))
    ).status_code == 200

    await authed_client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": "EMERGENCY_PROFILE", "granted": False, "policy_version": POLICY},
    )

    after = await authed_client.get("/api/v1/me/emergency-profile", headers=auth(token))
    assert after.status_code == 403


async def test_deleting_works_even_without_consent(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """Withdrawing data must never be harder than providing it."""
    await with_consent(authed_client, token)
    await authed_client.put("/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE)
    await authed_client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": "EMERGENCY_PROFILE", "granted": False, "policy_version": POLICY},
    )

    response = await authed_client.delete("/api/v1/me/emergency-profile", headers=auth(token))

    assert response.status_code == 204
    profile = (await authed_client.get("/api/v1/me", headers=auth(token))).json()["data"]
    assert profile["has_emergency_profile"] is False


async def test_deleting_twice_is_not_an_error(authed_client: httpx.AsyncClient, token: str) -> None:
    """A client retrying after a timeout must get the same answer."""
    first = await authed_client.delete("/api/v1/me/emergency-profile", headers=auth(token))
    second = await authed_client.delete("/api/v1/me/emergency-profile", headers=auth(token))

    assert first.status_code == second.status_code == 204


# --- ownership ------------------------------------------------------------------------------------


async def test_one_user_cannot_read_anothers_profile(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    mine = key.sign({"sub": f"emergency-{uuid.uuid4()}"})
    theirs = key.sign({"sub": f"emergency-{uuid.uuid4()}"})

    await with_consent(authed_client, mine)
    await authed_client.put("/api/v1/me/emergency-profile", headers=auth(mine), json=PROFILE)

    await with_consent(authed_client, theirs)
    response = await authed_client.get("/api/v1/me/emergency-profile", headers=auth(theirs))

    assert response.status_code == 404
    assert "penicillin" not in response.text


async def test_reading_without_a_profile_is_a_404(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    await with_consent(authed_client, token)

    assert (
        await authed_client.get("/api/v1/me/emergency-profile", headers=auth(token))
    ).status_code == 404


async def test_the_endpoint_needs_authentication(authed_client: httpx.AsyncClient) -> None:
    assert (await authed_client.get("/api/v1/me/emergency-profile")).status_code == 401
    assert (
        await authed_client.put("/api/v1/me/emergency-profile", json=PROFILE)
    ).status_code == 401


# --- validation -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"blood_type": "Z+"},
        {"medical_notes": "x" * 2001},
        {"allergies": ["x" * 129]},
        {"contacts": [{"name": "No phone"}]},
        {"unexpected_field": "value"},
    ],
)
async def test_invalid_payloads_are_rejected(
    authed_client: httpx.AsyncClient, token: str, body: dict[str, Any]
) -> None:
    await with_consent(authed_client, token)

    response = await authed_client.put(
        "/api/v1/me/emergency-profile", headers=auth(token), json=body
    )

    assert response.status_code == 400


async def test_a_rejected_payload_is_not_echoed_back(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """A validation error must not become the thing that leaks the medical note."""
    await with_consent(authed_client, token)

    response = await authed_client.put(
        "/api/v1/me/emergency-profile",
        headers=auth(token),
        json={"blood_type": "Z+", "medical_notes": "Highly identifying detail."},
    )

    assert response.status_code == 400
    assert "Highly identifying detail" not in response.text


# --- audit and logs -------------------------------------------------------------------------------


async def test_the_audit_entry_records_counts_not_contents(
    authed_client: httpx.AsyncClient, token: str, db_session: Any
) -> None:
    await with_consent(authed_client, token)
    await authed_client.put("/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE)

    details = (
        await db_session.execute(
            text(
                "SELECT details::text FROM identity.audit_log "
                "WHERE action = 'EMERGENCY_PROFILE_WRITTEN' ORDER BY occurred_at DESC LIMIT 1"
            )
        )
    ).scalar_one()

    assert '"allergy_count": 2' in details.replace('"allergy_count":2', '"allergy_count": 2')
    for secret in ("penicillin", "peanuts", "adrenaline", "Somchai", "66812345678"):
        assert secret not in details


async def test_nothing_from_the_profile_reaches_the_logs(
    authed_client: httpx.AsyncClient, token: str, capsys: pytest.CaptureFixture[str]
) -> None:
    await with_consent(authed_client, token)
    await authed_client.put("/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE)
    await authed_client.get("/api/v1/me/emergency-profile", headers=auth(token))

    captured = capsys.readouterr()
    output = captured.out + captured.err
    for secret in ("penicillin", "peanuts", "adrenaline", "Somchai", "66812345678", "EX-123456"):
        assert secret not in output, f"{secret!r} reached the logs"


# --- no key configured ----------------------------------------------------------------------------


async def test_without_a_key_the_endpoint_refuses_rather_than_storing_plaintext(
    live_settings: Any, key: SigningKeyPair
) -> None:
    """The failure this whole design exists to prevent.

    A deployment that forgot the key must not quietly write medical notes in the clear. It reports
    the feature as unavailable and says nothing was stored.
    """
    from app.main import create_app

    settings = build_settings(
        POSTGRES_HOST=live_settings.postgres_host,
        POSTGRES_PORT=str(live_settings.postgres_port),
        POSTGRES_DB=live_settings.postgres_db,
        POSTGRES_USER=live_settings.postgres_user,
        POSTGRES_PASSWORD=live_settings.postgres_password.get_secret_value(),
        API_EMERGENCY_ENCRYPTION_KEYS="",
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        # After the lifespan, not before: startup builds the real JWKS cache and would overwrite
        # a stub installed earlier.
        app.state.jwks = StubJwks.containing(key)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            token = key.sign({"sub": f"nokey-{uuid.uuid4()}"})
            await client.post(
                "/api/v1/consents",
                headers=auth(token),
                json={"type": "EMERGENCY_PROFILE", "granted": True, "policy_version": POLICY},
            )
            response = await client.put(
                "/api/v1/me/emergency-profile", headers=auth(token), json=PROFILE
            )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "clear" in response.json()["error"]["message"]
