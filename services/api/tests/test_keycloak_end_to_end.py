"""The phase 2 exit criterion: a protected endpoint reached with a token Keycloak actually issued.

Nothing here is substituted. The realm is the one imported from
`infra/keycloak/smart-travel-realm.json`, the token is signed by Keycloak's own key, the JWKS is
fetched over the network by the real cache, and the profile lands in real PostgreSQL. Every earlier
test could pass against a realm that does not exist; this one cannot.

No credential is committed anywhere. The test user is created at runtime through the admin API,
with a random password, and is deleted afterwards.
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from tests.database import requires_database

pytestmark = [pytest.mark.integration, requires_database]

REALM = "smart-travel"
TEST_CLIENT_ID = "smart-travel-test-cli"


def keycloak_base_url() -> str:
    """Where Keycloak is, inside compose or from a laptop."""
    return os.environ.get("KEYCLOAK_BASE_URL", "http://localhost:8080").rstrip("/")


def issuer_url() -> str:
    return f"{keycloak_base_url()}/realms/{REALM}"


async def keycloak_is_reachable() -> bool:
    """The realm has to exist, not just the server: an unimported realm answers 404."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{issuer_url()}/.well-known/openid-configuration")
        return response.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
async def keycloak_available() -> bool:
    available = await keycloak_is_reachable()
    if not available:
        pytest.skip(
            f"no Keycloak realm at {issuer_url()}. Start it with:\n"
            "  docker compose -f compose.yaml -f compose.dev.yaml --profile core up -d --wait"
        )
    return available


@pytest.fixture(scope="module")
async def admin_token(keycloak_available: bool) -> str:
    """An admin token, from the bootstrap credentials the local stack already has.

    Read from the environment, never from a file in the repository.
    """
    username = os.environ.get("KEYCLOAK_ADMIN", "admin")
    password = os.environ.get("KEYCLOAK_ADMIN_PASSWORD")
    if not password:
        pytest.skip("KEYCLOAK_ADMIN_PASSWORD is not set; cannot provision a test user")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{keycloak_base_url()}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            },
        )
    response.raise_for_status()
    return str(response.json()["access_token"])


@pytest.fixture
async def test_user(admin_token: str) -> AsyncIterator[tuple[str, str]]:
    """Create a throwaway realm user, yield its credentials, delete it afterwards.

    The password is generated per run and never leaves this process, so nothing is committed and
    nothing survives the test.
    """
    username = f"pytest-{uuid.uuid4().hex[:12]}"
    password = secrets.token_urlsafe(24)
    admin = f"{keycloak_base_url()}/admin/realms/{REALM}/users"
    headers = {"Authorization": f"Bearer {admin_token}"}

    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        created = await client.post(
            admin,
            json={
                "username": username,
                "enabled": True,
                # A user missing any of these is "not fully set up" as far as Keycloak's
                # verify-profile action is concerned, and the password grant refuses it with
                # invalid_grant — which looks like a credential problem and is not one.
                "email": f"{username}@example.invalid",
                "emailVerified": True,
                "firstName": "Pytest",
                "lastName": "User",
                "requiredActions": [],
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            },
        )
        created.raise_for_status()
        user_id = created.headers["Location"].rsplit("/", 1)[-1]

        try:
            yield username, password
        finally:
            await client.delete(f"{admin}/{user_id}")


async def request_token(username: str, password: str, *, scope: str) -> httpx.Response:
    """A password grant against the local-only test client. No client secret: it is public."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await client.post(
            f"{issuer_url()}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": TEST_CLIENT_ID,
                "username": username,
                "password": password,
                "scope": scope,
            },
        )


@pytest.fixture
async def keycloak_app(live_settings: Any) -> AsyncIterator[FastAPI]:
    """The real app, pointed at the real realm, with the real JWKS cache."""
    from app.main import create_app
    from tests.conftest import build_settings

    settings = build_settings(
        OIDC_ISSUER=issuer_url(),
        POSTGRES_HOST=live_settings.postgres_host,
        POSTGRES_PORT=str(live_settings.postgres_port),
        POSTGRES_DB=live_settings.postgres_db,
        POSTGRES_USER=live_settings.postgres_user,
        POSTGRES_PASSWORD=live_settings.postgres_password.get_secret_value(),
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def keycloak_client(keycloak_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=keycloak_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# --- the exit criterion ------------------------------------------------------------------------


async def test_a_real_keycloak_token_reaches_a_protected_endpoint(
    keycloak_client: httpx.AsyncClient, test_user: tuple[str, str]
) -> None:
    """Phase 2 exit: sign in for real, call a protected endpoint, get a real user id back."""
    username, password = test_user
    token_response = await request_token(username, password, scope="openid travel")
    assert token_response.status_code == 200, token_response.text
    access_token = token_response.json()["access_token"]

    response = await keycloak_client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert uuid.UUID(body["data"]["user_id"])
    assert body["data"]["consents"] == []  # phase 3; no consent can be granted yet
    assert body["data"]["has_emergency_profile"] is False


async def test_the_realm_grants_the_traveller_role_by_default(
    test_user: tuple[str, str],
) -> None:
    """A user who has just signed up must be able to use the product without an admin step."""
    import jwt

    username, password = test_user
    token = (await request_token(username, password, scope="openid travel")).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})

    assert "traveller" in claims["realm_access"]["roles"]


async def test_the_token_carries_this_services_audience(test_user: tuple[str, str]) -> None:
    """Without the audience mapper, a token meant for this API would be indistinguishable from
    one meant for any other client in the realm."""
    import jwt

    username, password = test_user
    token = (await request_token(username, password, scope="openid travel")).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})

    audience = claims["aud"]
    audiences = audience if isinstance(audience, list) else [audience]
    assert "smart-travel-api" in audiences


async def test_a_real_token_without_the_travel_scope_is_forbidden(
    keycloak_client: httpx.AsyncClient, test_user: tuple[str, str]
) -> None:
    """`travel` is an optional client scope, so a client can genuinely ask for less.

    The token is valid and the audience is right; only the grant is narrower. That is 403.
    """
    username, password = test_user
    token = (await request_token(username, password, scope="openid")).json()["access_token"]

    response = await keycloak_client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_the_jwks_is_fetched_from_the_real_provider(keycloak_app: FastAPI) -> None:
    """The cache resolved discovery and pulled real keys — no stub anywhere in this test."""
    cache = keycloak_app.state.jwks
    await cache.warm()

    assert cache._entry is not None, "no keys were fetched"
    assert cache._entry.keys_by_kid, "the provider published no keys"


async def test_a_token_from_the_master_realm_is_rejected(
    keycloak_client: httpx.AsyncClient, admin_token: str
) -> None:
    """A real, unexpired, correctly signed token — from the wrong realm.

    This is the check that makes the issuer comparison worth having: the signature is valid, just
    not by a key this realm published.
    """
    response = await keycloak_client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {admin_token}"}
    )

    assert response.status_code == 401


async def test_readiness_is_green_once_the_realm_exists(
    keycloak_client: httpx.AsyncClient,
) -> None:
    """Phase 1 left readiness red because the realm did not exist. It should be green now.

    The agent service is still absent, but it is an optional dependency, so it must not hold
    readiness down.
    """
    response = await keycloak_client.get("/health/ready")
    body = response.json()

    by_name = {check["name"]: check for check in body["checks"]}
    assert by_name["oidc"]["status"] == "up", body
    assert by_name["postgres"]["status"] == "up", body
