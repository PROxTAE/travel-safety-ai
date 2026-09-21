"""Profile updates and consent, over HTTP against a real database.

The behaviours here are the ones a reviewer cannot confirm by reading the handler: that a PATCH
omitting a field leaves it alone, that a consent decision supersedes the last one without losing
it, that a location grant is capped whatever the client asks for, and that the audit trail records
what happened without recording what it said.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]

POLICY = "1.0.0"


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
    """One freshly-created user per test, so tests cannot see each other's rows."""
    return key.sign({"sub": f"phase3-{uuid.uuid4()}"})


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def grant(client: httpx.AsyncClient, token: str, consent_type: str, **extra: Any) -> Any:
    return await client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": consent_type, "granted": True, "policy_version": POLICY, **extra},
    )


# --- PATCH /me ------------------------------------------------------------------------------------


async def test_a_profile_field_can_be_changed(authed_client: httpx.AsyncClient, token: str) -> None:
    response = await authed_client.patch(
        "/api/v1/me", headers=auth(token), json={"timezone": "Asia/Bangkok"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["timezone"] == "Asia/Bangkok"


async def test_a_patch_leaves_untouched_fields_alone(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """The failure mode `exclude_unset` exists to prevent: a partial update wiping the rest."""
    await authed_client.patch(
        "/api/v1/me",
        headers=auth(token),
        json={"timezone": "Asia/Bangkok", "locale": "th-TH", "home_country_code": "TH"},
    )

    response = await authed_client.patch(
        "/api/v1/me", headers=auth(token), json={"locale": "en-GB"}
    )

    data = response.json()["data"]
    assert data["locale"] == "en-GB"
    assert data["timezone"] == "Asia/Bangkok", "an omitted field was reset"
    assert data["home_country_code"] == "TH", "an omitted field was reset"


async def test_an_empty_patch_is_accepted(authed_client: httpx.AsyncClient, token: str) -> None:
    """What a client that computed no diff sends. It must not be an error."""
    response = await authed_client.patch("/api/v1/me", headers=auth(token), json={})

    assert response.status_code == 200


async def test_a_timezone_that_is_not_in_the_tz_database_is_rejected(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """`Asia/Bangkgok` is a plausible-looking string that would break every departure time."""
    response = await authed_client.patch(
        "/api/v1/me", headers=auth(token), json={"timezone": "Asia/Bangkgok"}
    )

    assert response.status_code == 400
    assert {item["path"] for item in response.json()["error"]["field_errors"]} == {"timezone"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("locale", "not a locale"),
        ("home_country_code", "TOOLONG"),
        ("home_country_code", "1A"),
    ],
)
async def test_invalid_profile_values_are_rejected(
    authed_client: httpx.AsyncClient, token: str, field: str, value: str
) -> None:
    response = await authed_client.patch("/api/v1/me", headers=auth(token), json={field: value})

    assert response.status_code == 400


async def test_a_lowercase_country_code_is_stored_uppercase(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """The contract says uppercase; "th" means Thailand as clearly as "TH" does."""
    response = await authed_client.patch(
        "/api/v1/me", headers=auth(token), json={"home_country_code": "th"}
    )

    assert response.json()["data"]["home_country_code"] == "TH"


async def test_an_unknown_field_is_rejected_rather_than_ignored(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """Silently dropping it would leave the caller believing a change happened."""
    response = await authed_client.patch("/api/v1/me", headers=auth(token), json={"is_admin": True})

    assert response.status_code == 400


async def test_a_profile_change_is_audited_without_its_values(
    authed_client: httpx.AsyncClient, token: str, db_session: Any
) -> None:
    await authed_client.patch("/api/v1/me", headers=auth(token), json={"home_country_code": "TH"})

    row = (
        await db_session.execute(
            text(
                "SELECT action, details::text FROM identity.audit_log "
                "WHERE action = 'PROFILE_UPDATED' ORDER BY occurred_at DESC LIMIT 1"
            )
        )
    ).one()

    assert row[0] == "PROFILE_UPDATED"
    assert "home_country_code" in row[1], "the audit entry should name the field"
    assert "TH" not in row[1], "the audit entry recorded the value"


# --- POST /consents -------------------------------------------------------------------------------


async def test_a_consent_can_be_granted(authed_client: httpx.AsyncClient, token: str) -> None:
    response = await grant(authed_client, token, "ANALYTICS")

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["type"] == "ANALYTICS"
    assert data["granted"] is True
    assert data["policy_version"] == POLICY


async def test_a_granted_consent_appears_on_the_profile(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    await grant(authed_client, token, "ANALYTICS")

    profile = (await authed_client.get("/api/v1/me", headers=auth(token))).json()["data"]

    by_type = {item["type"]: item for item in profile["consents"]}
    assert by_type["ANALYTICS"]["granted"] is True


async def test_withdrawing_is_the_same_endpoint_and_no_harder(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """Making withdrawal harder than granting is a dark pattern, not an oversight to fix later."""
    await grant(authed_client, token, "ANALYTICS")

    response = await authed_client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": "ANALYTICS", "granted": False, "policy_version": POLICY},
    )

    assert response.status_code == 201
    profile = (await authed_client.get("/api/v1/me", headers=auth(token))).json()["data"]
    by_type = {item["type"]: item for item in profile["consents"]}
    assert by_type["ANALYTICS"]["granted"] is False


async def test_the_earlier_decision_is_kept_not_overwritten(
    authed_client: httpx.AsyncClient, token: str, db_session: Any
) -> None:
    """The reason this is a table and not a boolean: it has to answer what was agreed, and when."""
    await grant(authed_client, token, "ANALYTICS")
    await authed_client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": "ANALYTICS", "granted": False, "policy_version": POLICY},
    )

    rows = (
        await db_session.execute(
            text(
                "SELECT granted, revoked_at IS NOT NULL AS revoked FROM identity.consents "
                "WHERE type = 'ANALYTICS' ORDER BY granted_at"
            )
        )
    ).all()

    assert len(rows) >= 2, "the earlier decision was overwritten"
    assert rows[-2] == (True, True), "the superseded grant should be kept and marked revoked"
    assert rows[-1] == (False, False)


async def test_only_one_record_of_a_type_stands_at_a_time(
    authed_client: httpx.AsyncClient, token: str, db_session: Any
) -> None:
    for _ in range(3):
        await grant(authed_client, token, "ALERT_NOTIFICATION")

    standing = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM identity.consents "
                "WHERE type = 'ALERT_NOTIFICATION' AND revoked_at IS NULL"
            )
        )
    ).scalar_one()

    assert standing == 1


async def test_a_location_grant_is_capped_however_long_the_client_asks_for(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """A location grant that outlives its errand is indistinguishable from tracking."""
    far_future = datetime.now(UTC) + timedelta(days=365)

    response = await grant(authed_client, token, "LOCATION_ONCE", expires_at=far_future.isoformat())

    expires_at = datetime.fromisoformat(response.json()["data"]["expires_at"])
    assert expires_at < datetime.now(UTC) + timedelta(days=1), "the requested expiry was honoured"


async def test_a_location_grant_gets_an_expiry_even_when_none_is_asked_for(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    response = await grant(authed_client, token, "LOCATION_ONCE")

    assert response.json()["data"]["expires_at"] is not None


async def test_a_shorter_expiry_than_the_ceiling_is_honoured(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    """The cap is a ceiling, not an override: asking for less must work."""
    soon = datetime.now(UTC) + timedelta(minutes=5)

    response = await grant(authed_client, token, "LOCATION_LIVE", expires_at=soon.isoformat())

    expires_at = datetime.fromisoformat(response.json()["data"]["expires_at"])
    assert abs((expires_at - soon).total_seconds()) < 5


async def test_an_expiry_in_the_past_is_rejected(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)

    response = await grant(authed_client, token, "ANALYTICS", expires_at=past.isoformat())

    assert response.status_code == 400
    assert {item["path"] for item in response.json()["error"]["field_errors"]} == {"expires_at"}


async def test_an_unknown_consent_type_is_rejected(
    authed_client: httpx.AsyncClient, token: str
) -> None:
    response = await authed_client.post(
        "/api/v1/consents",
        headers=auth(token),
        json={"type": "READ_EVERYTHING", "granted": True, "policy_version": POLICY},
    )

    assert response.status_code == 400


async def test_the_policy_version_is_required(authed_client: httpx.AsyncClient, token: str) -> None:
    """A consent record without the version of the text shown proves nothing."""
    response = await authed_client.post(
        "/api/v1/consents", headers=auth(token), json={"type": "ANALYTICS", "granted": True}
    )

    assert response.status_code == 400


async def test_consent_requires_authentication(authed_client: httpx.AsyncClient) -> None:
    response = await authed_client.post(
        "/api/v1/consents", json={"type": "ANALYTICS", "granted": True, "policy_version": POLICY}
    )

    assert response.status_code == 401


async def test_one_users_consent_is_not_visible_to_another(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    mine = key.sign({"sub": f"phase3-{uuid.uuid4()}"})
    theirs = key.sign({"sub": f"phase3-{uuid.uuid4()}"})
    await grant(authed_client, mine, "ANALYTICS")

    profile = (await authed_client.get("/api/v1/me", headers=auth(theirs))).json()["data"]

    assert profile["consents"] == []
