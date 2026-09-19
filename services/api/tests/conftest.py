"""Test fixtures.

Two tiers, kept apart on purpose.

The **fast tier** drives the ASGI app directly with no database, no Redis and no identity provider.
It covers the middleware chain, the error envelope, the health endpoints and the token verifier —
everything that is pure logic. It runs in about a second, so it can gate every commit.

The **integration tier** is marked `integration` and needs a real PostgreSQL, and for a few tests a
real Keycloak. It covers identity resolution, ownership at the repository layer, and a token
genuinely issued by Keycloak. Those cannot be verified against a fake without the test becoming a
test of the fake.

Nothing here uses a real credential. The placeholder values are syntactically valid inputs that let
Settings construct against hosts that do not exist.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.engine import make_url

from app.security.envelope import EnvelopeCipher
from app.settings import Settings, get_settings
from tests.database import provision_database

SERVICE_ROOT = Path(__file__).resolve().parents[1]

#: The environment variables Alembic reads its URL from, via Settings.
_DB_ENV_KEYS = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)

TEST_ENV: dict[str, str] = {
    "APP_ENV": "test",
    "LOG_LEVEL": "INFO",
    "CONTRACT_VERSION": "1.0.0",
    "POSTGRES_HOST": "postgres.invalid",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "smart_travel_test",
    "POSTGRES_USER": "test_user",
    "POSTGRES_PASSWORD": "not-a-real-password",
    "REDIS_URL": "redis://redis.invalid:6379/0",
    "OIDC_ISSUER": "http://keycloak.invalid:8080/realms/smart-travel",
    "OIDC_AUDIENCE": "smart-travel-api",
    "API_CORS_ALLOWED_ORIGINS": "http://localhost:3000",
    "API_READINESS_TIMEOUT_SECONDS": "1",
    # Generated per run, never committed. A fixture key in the repository would be a key someone
    # eventually copies into a deployment.
    "API_EMERGENCY_ENCRYPTION_KEYS": f"v1:{EnvelopeCipher.generate_key()}",
}


def build_settings(**overrides: str) -> Settings:
    values = {key.lower(): value for key, value in TEST_ENV.items()}
    values.update({key.lower(): value for key, value in overrides.items()})
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return build_settings()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Put the test environment in place and clear the settings cache around it."""
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """An application instance with no lifespan run.

    Startup opens a database engine, a Redis client and an HTTP client. None of those is needed to
    test the middleware chain or the error envelope, and none of the hosts above exists, so the
    lifespan stays unrun and `readiness_checks` stays empty unless a test fills it.
    """
    from app.main import create_app

    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Drive the app in-process. No socket, no port, no race with a server start-up.

    `raise_app_exceptions=False` makes the transport behave like a real server: Starlette's error
    middleware re-raises after building the 500 response so the server can log it, and a test that
    let the exception escape would be asserting on something no client ever sees.
    """
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


# --- integration tier -------------------------------------------------------------------------


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A synchronous URL for a PostgreSQL that belongs to this session alone."""
    with provision_database() as url:
        yield url


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> str:
    """The same database, at migration head.

    Migrated once for the session: `alembic upgrade head` against a fresh database is the slowest
    thing in the suite, and re-running it per test would buy nothing — the tests that write clean
    up after themselves.
    """
    url = make_url(database_url)
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))

    previous = {key: os.environ.get(key) for key in _DB_ENV_KEYS}
    os.environ.update(
        {
            "POSTGRES_HOST": url.host or "localhost",
            "POSTGRES_PORT": str(url.port or 5432),
            "POSTGRES_DB": url.database or "postgres",
            "POSTGRES_USER": url.username or "postgres",
            "POSTGRES_PASSWORD": url.password or "",
        }
    )
    get_settings.cache_clear()
    try:
        command.upgrade(config, "head")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    return database_url


@pytest.fixture
def live_settings(migrated_database_url: str) -> Settings:
    """Settings pointing at the migrated database."""
    url = make_url(migrated_database_url)
    return build_settings(
        POSTGRES_HOST=url.host or "localhost",
        POSTGRES_PORT=str(url.port or 5432),
        POSTGRES_DB=url.database or "postgres",
        POSTGRES_USER=url.username or "postgres",
        POSTGRES_PASSWORD=url.password or "",
    )


@pytest.fixture
async def live_app(live_settings: Settings) -> AsyncIterator[FastAPI]:
    """The real application against the real database, with its lifespan run.

    Nothing about startup is stubbed. Redis and the identity provider are unreachable from here,
    which is exactly the condition the lifespan is written to survive: it opens lazy clients and
    the JWKS warm-up swallows its own failure.
    """
    from app.main import create_app

    application = create_app(live_settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def live_client(live_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=live_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
async def db_session(live_app: FastAPI) -> AsyncIterator[Any]:
    """A session on the same engine the app uses, committed at the end of the test."""
    from app.db.engine import session_scope

    async with session_scope(live_app.state.session_factory) as session:
        yield session


def random_subject() -> str:
    """A unique OIDC subject, so tests that create profiles cannot collide."""
    return f"test-subject-{uuid.uuid4()}"


def envelope_meta(payload: dict[str, Any]) -> dict[str, Any]:
    """The `meta` block, asserted on in several places."""
    assert "meta" in payload, f"response has no meta block: {payload}"
    return payload["meta"]
