"""Test fixtures for the API scaffold.

These tests exercise the HTTP surface without a database. That is a deliberate boundary: phase 1
builds the app factory, the middleware chain, the error envelope and the health endpoints, and all
of those are testable against the ASGI app directly. Tests that need real PostgreSQL are marked
`integration` and are skipped when Docker is not available, so the fast suite stays fast and the
slow one stays honest.

Nothing here uses a real credential. The placeholder values below are not secrets; they are
syntactically valid inputs that let Settings construct.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.settings import Settings

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
    "API_CORS_ALLOWED_ORIGINS": "http://localhost:3000",
    "API_READINESS_TIMEOUT_SECONDS": "1",
}


@pytest.fixture
def settings() -> Settings:
    return Settings(**{key.lower(): value for key, value in TEST_ENV.items()})  # type: ignore[arg-type]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Put the test environment in place and clear the settings cache around it."""
    from app.settings import get_settings

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


@pytest.fixture
def docker_available() -> bool:
    return os.environ.get("DOCKER_HOST") is not None or os.path.exists("/var/run/docker.sock")


def envelope_meta(payload: dict[str, Any]) -> dict[str, Any]:
    """The `meta` block, asserted on in several places."""
    assert "meta" in payload, f"response has no meta block: {payload}"
    return payload["meta"]
