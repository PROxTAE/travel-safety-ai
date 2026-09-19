"""Health endpoints.

The distinction under test: liveness must never depend on anything external, and readiness must
fail when a required dependency is down while tolerating an optional one that is.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.health.checks import DependencyCheck, run_all


async def test_live_answers_without_any_dependency(client: httpx.AsyncClient) -> None:
    """No lifespan has run: no database, no Redis, no HTTP client. Liveness must still be true."""
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


async def test_live_reports_service_identity(client: httpx.AsyncClient) -> None:
    body = await client.get("/health/live")
    payload = body.json()

    assert payload["service"] == "api"
    assert payload["version"]


async def test_ready_is_true_when_every_required_check_passes(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async def ok() -> None:
        return None

    app.state.readiness_checks = [
        DependencyCheck(name="postgres", required=True, probe=ok, timeout_seconds=1),
        DependencyCheck(name="redis", required=True, probe=ok, timeout_seconds=1),
    ]

    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_ready_is_false_when_a_required_dependency_is_down(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """503, so the orchestrator takes this instance out of rotation instead of sending it work."""

    async def ok() -> None:
        return None

    async def fails() -> None:
        raise ConnectionRefusedError("connection refused")

    app.state.readiness_checks = [
        DependencyCheck(name="postgres", required=True, probe=fails, timeout_seconds=1),
        DependencyCheck(name="redis", required=True, probe=ok, timeout_seconds=1),
    ]

    response = await client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    statuses = {check["name"]: check["status"] for check in payload["checks"]}
    assert statuses == {"postgres": "down", "redis": "up"}


async def test_optional_dependency_failure_does_not_make_the_service_unready(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Assessments need the agent; profiles, trips and emergency contacts do not.

    Reporting the whole API as unready for a partial outage would take down the screens someone
    might open precisely because something has gone wrong.
    """

    async def ok() -> None:
        return None

    async def fails() -> None:
        raise ConnectionRefusedError

    app.state.readiness_checks = [
        DependencyCheck(name="postgres", required=True, probe=ok, timeout_seconds=1),
        DependencyCheck(name="agent", required=False, probe=fails, timeout_seconds=1),
    ]

    response = await client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    agent = next(check for check in payload["checks"] if check["name"] == "agent")
    assert agent["status"] == "down"
    assert agent["required"] is False


async def test_a_hung_dependency_does_not_hang_the_probe(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """A probe that never answers is read as a dead container, so the budget is enforced."""

    async def never_answers() -> None:
        await asyncio.sleep(60)

    app.state.readiness_checks = [
        DependencyCheck(name="postgres", required=True, probe=never_answers, timeout_seconds=0.1),
    ]

    response = await asyncio.wait_for(client.get("/health/ready"), timeout=5)

    assert response.status_code == 503
    assert response.json()["checks"][0]["status"] == "down"


async def test_check_detail_never_leaks_connection_information() -> None:
    """`/health/ready` is unauthenticated, and a driver's error message carries the DSN."""

    async def fails() -> None:
        raise ConnectionRefusedError(
            "could not connect to postgresql://admin:hunter2@postgres:5432/smart_travel"
        )

    _, results = await run_all(
        [DependencyCheck(name="postgres", required=True, probe=fails, timeout_seconds=1)],
        budget_seconds=1,
    )

    detail = results[0].detail or ""
    assert "hunter2" not in detail
    assert "postgresql://" not in detail
    assert "ConnectionRefusedError" in detail


async def test_whole_probe_respects_its_budget() -> None:
    """Checks that outrun the budget are reported down, not silently omitted."""

    async def slow() -> None:
        await asyncio.sleep(5)

    ready, results = await run_all(
        [DependencyCheck(name="slow", required=True, probe=slow, timeout_seconds=10)],
        budget_seconds=0.2,
    )

    assert ready is False
    assert results[0].status == "down"
    assert results[0].detail == "exceeded the readiness budget"


async def test_metrics_endpoint_exposes_the_service_registry(client: httpx.AsyncClient) -> None:
    await client.get("/health/live")
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "api_http_requests_total" in response.text


async def test_metrics_label_the_route_template_not_the_path(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """A trip id in a metric label creates one time series per trip."""
    await client.get("/health/live")
    body = (await client.get("/metrics")).text

    assert 'route="/health/live"' in body


@pytest.mark.parametrize("path", ["/health/live", "/health/ready", "/metrics"])
async def test_health_endpoints_need_no_authentication(
    app: FastAPI, client: httpx.AsyncClient, path: str
) -> None:
    """They are probed by the orchestrator, which has no token."""
    app.state.readiness_checks = []
    response = await client.get(path)

    assert response.status_code != 401
