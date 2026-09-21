"""Authentication and authorisation over HTTP, against a real database.

The token verifier is unit-tested elsewhere. What these tests cover is the part that only exists
once the pieces are wired together: that a verified subject becomes a local user, that the scope
check answers 403 rather than 401, that a disabled account stops working while its token is still
valid, and that one user's request cannot return another user's row.

The database is real. Only the key source is substituted — the same substitution an HTTP mock of
the JWKS endpoint would make, and the verification code under test is untouched.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from tests.database import requires_database
from tests.keys import SigningKeyPair, StubJwks

pytestmark = [pytest.mark.integration, requires_database]


@pytest.fixture(scope="module")
def key() -> SigningKeyPair:
    return SigningKeyPair.generate()


@pytest.fixture
def authed_app(live_app: FastAPI, key: SigningKeyPair) -> FastAPI:
    """The real app, with the JWKS cache replaced by a key source under the test's control."""
    live_app.state.jwks = StubJwks.containing(key)
    return live_app


@pytest.fixture
async def authed_client(authed_app: FastAPI) -> Any:
    transport = httpx.ASGITransport(app=authed_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def new_subject() -> str:
    return f"keycloak-subject-{uuid.uuid4()}"


# --- the chain works --------------------------------------------------------------------------


async def test_a_valid_token_reaches_the_endpoint(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    response = await authed_client.get(
        "/api/v1/me", headers=bearer(key.sign({"sub": new_subject()}))
    )

    assert response.status_code == 200
    body = response.json()
    assert uuid.UUID(body["data"]["user_id"])
    assert body["meta"]["contract_version"] == "1.0.0"


async def test_first_sign_in_creates_the_profile_and_later_ones_reuse_it(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    """The subject is the external identity; the internal id is what everything else joins on."""
    subject = new_subject()
    token = key.sign({"sub": subject})

    first = await authed_client.get("/api/v1/me", headers=bearer(token))
    second = await authed_client.get("/api/v1/me", headers=bearer(token))

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["user_id"] == second.json()["data"]["user_id"]


async def test_two_subjects_get_two_different_users(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    one = await authed_client.get("/api/v1/me", headers=bearer(key.sign({"sub": new_subject()})))
    two = await authed_client.get("/api/v1/me", headers=bearer(key.sign({"sub": new_subject()})))

    assert one.json()["data"]["user_id"] != two.json()["data"]["user_id"]


async def test_the_response_carries_only_the_callers_own_row(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    """`/me` has no id parameter, so "read someone else's profile" is not expressible.

    This is the ownership guarantee at the HTTP level: the row is chosen by the id in the
    principal, never by anything the client sent.
    """
    mine = await authed_client.get("/api/v1/me", headers=bearer(key.sign({"sub": new_subject()})))
    theirs = await authed_client.get("/api/v1/me", headers=bearer(key.sign({"sub": new_subject()})))

    my_id = mine.json()["data"]["user_id"]
    their_id = theirs.json()["data"]["user_id"]
    assert my_id != their_id
    assert their_id not in mine.text


async def test_the_display_name_comes_from_the_token_and_is_not_stored(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, db_session: Any
) -> None:
    """The name belongs to the identity provider; a second copy here is personal data we would
    then have to protect, migrate and delete."""
    subject = new_subject()
    response = await authed_client.get(
        "/api/v1/me", headers=bearer(key.sign({"sub": subject, "name": "Ada Lovelace"}))
    )

    assert response.json()["data"]["display_name"] == "Ada Lovelace"

    columns = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'identity' AND table_name = 'user_profiles'"
        )
    )
    stored = {row[0] for row in columns}
    assert "display_name" not in stored
    assert "email" not in stored


# --- authentication failures ------------------------------------------------------------------


async def test_no_token_is_rejected(authed_client: httpx.AsyncClient) -> None:
    response = await authed_client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "token abc"},
    ],
)
async def test_a_non_bearer_authorization_header_is_rejected(
    authed_client: httpx.AsyncClient, header: dict[str, str]
) -> None:
    response = await authed_client.get("/api/v1/me", headers=header)

    assert response.status_code == 401


async def test_an_expired_token_is_rejected_over_http(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    now = int(time.time())
    expired = key.sign(
        {"sub": new_subject(), "iat": now - 7200, "nbf": now - 7200, "exp": now - 3600}
    )

    response = await authed_client.get("/api/v1/me", headers=bearer(expired))

    assert response.status_code == 401


async def test_every_rejection_looks_the_same_from_outside(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    """A caller that could tell expiry from a wrong audience could map the configuration."""
    now = int(time.time())
    tokens = [
        # Well past the leeway. `now - 10` would be tolerated on purpose, which another test
        # asserts, and using it here would make this test fail for the wrong reason.
        key.sign({"sub": new_subject(), "exp": now - 3600, "iat": now - 7200, "nbf": now - 7200}),
        key.sign({"sub": new_subject(), "iss": "https://elsewhere.invalid/realms/x"}),
        key.sign({"sub": new_subject(), "aud": "another-service"}),
        SigningKeyPair.generate(kid="unpublished").sign({"sub": new_subject()}),
    ]

    bodies = set()
    for token in tokens:
        response = await authed_client.get("/api/v1/me", headers=bearer(token))
        assert response.status_code == 401
        bodies.add(response.json()["error"]["message"])

    assert len(bodies) == 1, f"the rejection reason is distinguishable: {bodies}"


# --- authorisation ----------------------------------------------------------------------------


async def test_a_token_without_the_travel_scope_is_forbidden_not_unauthorised(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    """403, not 401.

    401 tells the client to refresh, which returns a token with the same scopes, and the client
    loops. 403 says the problem is the grant, which is something a user can act on.
    """
    response = await authed_client.get(
        "/api/v1/me", headers=bearer(key.sign({"sub": new_subject(), "scope": "openid profile"}))
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_the_forbidden_response_does_not_name_the_missing_scope(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    """Which scope is missing is a configuration detail; it belongs in the log, not the response."""
    response = await authed_client.get(
        "/api/v1/me", headers=bearer(key.sign({"sub": new_subject(), "scope": "openid"}))
    )

    assert "travel" not in response.text


# --- a token cannot be withdrawn, so the local row has the last word ----------------------------


async def test_a_disabled_account_is_refused_while_its_token_is_still_valid(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, db_session: Any
) -> None:
    """The reason `disabled_at` exists.

    A JWT stays valid until it expires. Without this check, disabling an account would do nothing
    for up to the token lifetime.
    """
    subject = new_subject()
    token = key.sign({"sub": subject})

    assert (await authed_client.get("/api/v1/me", headers=bearer(token))).status_code == 200

    await db_session.execute(
        text("UPDATE identity.user_profiles SET disabled_at = now() WHERE subject_id = :subject"),
        {"subject": subject},
    )
    await db_session.commit()

    after = await authed_client.get("/api/v1/me", headers=bearer(token))
    assert after.status_code == 401


async def test_a_soft_deleted_account_is_refused(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, db_session: Any
) -> None:
    subject = new_subject()
    token = key.sign({"sub": subject})
    assert (await authed_client.get("/api/v1/me", headers=bearer(token))).status_code == 200

    await db_session.execute(
        text("UPDATE identity.user_profiles SET deleted_at = now() WHERE subject_id = :subject"),
        {"subject": subject},
    )
    await db_session.commit()

    after = await authed_client.get("/api/v1/me", headers=bearer(token))
    assert after.status_code == 401


# --- the rest of the surface -------------------------------------------------------------------


async def test_health_endpoints_stay_unauthenticated(authed_client: httpx.AsyncClient) -> None:
    """The orchestrator has no token. Authentication is per-router, so this is a real check that
    the new router did not accidentally cover them."""
    for path in ("/health/live", "/metrics"):
        assert (await authed_client.get(path)).status_code == 200


async def test_an_authentication_failure_is_counted(
    authed_client: httpx.AsyncClient, key: SigningKeyPair
) -> None:
    """A spike in one reason is the signal worth alerting on."""
    await authed_client.get("/api/v1/me")
    await authed_client.get(
        "/api/v1/me", headers=bearer(key.sign({"sub": new_subject(), "scope": "openid"}))
    )

    metrics = (await authed_client.get("/metrics")).text

    assert 'api_auth_failures_total{reason="missing_token"}' in metrics
    assert 'api_auth_failures_total{reason="missing_scope"}' in metrics


async def test_the_token_never_reaches_the_logs(
    authed_client: httpx.AsyncClient, key: SigningKeyPair, capsys: pytest.CaptureFixture[str]
) -> None:
    token = key.sign({"sub": new_subject()})
    await authed_client.get("/api/v1/me", headers=bearer(token))

    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err
