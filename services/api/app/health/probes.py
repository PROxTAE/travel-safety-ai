"""The concrete dependency probes, and which ones readiness insists on.

Each probe does the smallest thing that proves the dependency is genuinely usable. Opening a TCP
connection is not enough: a PostgreSQL that accepts connections while refusing queries, or a
Keycloak still loading its realm, would both pass a socket check and fail a real request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.health.checks import DependencyCheck

if TYPE_CHECKING:
    from app.settings import Settings


def database_check(engine: AsyncEngine, settings: Settings) -> DependencyCheck:
    """Run a trivial query, not just a connection open.

    `SELECT 1` proves the connection is usable end to end: authenticated, not in a failed
    transaction, and able to return a result.
    """

    async def probe() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    return DependencyCheck(
        name="postgres",
        required=True,
        probe=probe,
        timeout_seconds=settings.db_connect_timeout_seconds,
    )


def redis_check(client: Redis, settings: Settings) -> DependencyCheck:
    """Redis is required even though it is not a system of record.

    Rate limiting, idempotency and run status all depend on it. Serving traffic without it would
    mean accepting duplicate assessments and losing the protection that stops one client from
    exhausting a provider quota for everyone.
    """

    async def probe() -> None:
        await client.ping()

    return DependencyCheck(
        name="redis",
        required=True,
        probe=probe,
        timeout_seconds=settings.redis_timeout_seconds,
    )


def oidc_discovery_check(client: httpx.AsyncClient, settings: Settings) -> DependencyCheck:
    """Fetch the OIDC discovery document.

    Required: without it no token can be verified, so every authenticated request would fail. The
    URL is built from configuration and never from a request.
    """

    async def probe() -> None:
        response = await client.get(
            settings.oidc_discovery_url, timeout=settings.oidc_discovery_timeout_seconds
        )
        response.raise_for_status()

    return DependencyCheck(
        name="oidc",
        required=True,
        probe=probe,
        timeout_seconds=settings.oidc_discovery_timeout_seconds,
    )


def agent_check(client: httpx.AsyncClient, settings: Settings) -> DependencyCheck:
    """Probe the agent service, but do not require it.

    If the agent is down, assessments cannot start — yet profiles, trips, consent and the emergency
    screens still work. Reporting the whole API as unready would take those down too, which is a
    worse outcome for someone who opened the app to find an emergency number.
    """

    async def probe() -> None:
        response = await client.get(
            f"{settings.agent_service_url}/health/live",
            timeout=settings.downstream_connect_timeout_seconds,
        )
        response.raise_for_status()

    return DependencyCheck(
        name="agent",
        required=False,
        probe=probe,
        timeout_seconds=settings.downstream_connect_timeout_seconds,
    )
