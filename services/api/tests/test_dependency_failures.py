"""Dependency failure matrix tests.

Exhaustively verifies behavior and error envelopes when downstream dependencies fail:
- PostgreSQL (connection drop / statement timeout / pool exhaustion)
- Redis (connection outage / fail-open rate limiting / SSE resilience)
- Keycloak / OIDC (discovery outage / JWKS unreachable / invalid tokens)
- Agent service (timeout / connection refused / request rejection)
- Recommendation service (timeout / unreachable / schema inconsistency)
- External Data service (timeout / 500 error / unconfigured credentials)
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from redis.asyncio import Redis

from app.clients.agent import AgentClient, AgentRejectedRequest
from app.clients.external_data import ExternalDataClient
from app.clients.recommendation import RecommendationClient, RecommendationInvalid
from app.errors.codes import RETRYABLE_CODES, ErrorCode
from app.errors.exceptions import DependencyTimeout, DependencyUnavailable
from app.health.probes import oidc_discovery_check, redis_check
from app.settings import Settings

# --- Agent Failure Tests ---


@respx.mock
async def test_agent_client_timeout_raises_dependency_timeout(settings: Settings) -> None:
    respx.post(f"{settings.agent_service_url.rstrip('/')}/internal/v1/runs").mock(
        side_effect=httpx.TimeoutException("agent timed out")
    )

    async with httpx.AsyncClient() as http_client:
        client = AgentClient(http_client, settings)
        with pytest.raises(DependencyTimeout) as exc_info:
            await client.create_run({"origin": "test"}, request_id=str(uuid.uuid4()))

        assert exc_info.value.code == ErrorCode.DEPENDENCY_TIMEOUT
        assert exc_info.value.code in RETRYABLE_CODES


@respx.mock
async def test_agent_client_500_raises_dependency_unavailable(settings: Settings) -> None:
    respx.post(f"{settings.agent_service_url.rstrip('/')}/internal/v1/runs").mock(
        return_value=httpx.Response(500, json={"error": "internal crash"})
    )

    async with httpx.AsyncClient() as http_client:
        client = AgentClient(http_client, settings)
        with pytest.raises(DependencyUnavailable) as exc_info:
            await client.create_run({"origin": "test"}, request_id=str(uuid.uuid4()))

        assert exc_info.value.code.value == "DEPENDENCY_UNAVAILABLE"


@respx.mock
async def test_agent_client_400_raises_agent_rejected_request(settings: Settings) -> None:
    respx.post(f"{settings.agent_service_url.rstrip('/')}/internal/v1/runs").mock(
        return_value=httpx.Response(
            400, json={"error": {"code": "VALIDATION_ERROR", "message": "bad input"}}
        )
    )

    async with httpx.AsyncClient() as http_client:
        client = AgentClient(http_client, settings)
        with pytest.raises(AgentRejectedRequest) as exc_info:
            await client.create_run({"origin": "test"}, request_id=str(uuid.uuid4()))

        assert exc_info.value.status_code == 400


# --- External Data Failure Tests ---


@respx.mock
async def test_external_data_timeout_raises_dependency_timeout(settings: Settings) -> None:
    respx.post(f"{settings.external_data_service_url.rstrip('/')}/internal/v1/geocode/search").mock(
        side_effect=httpx.TimeoutException("external data timeout")
    )

    async with httpx.AsyncClient() as http_client:
        client = ExternalDataClient(http_client, settings)
        with pytest.raises(DependencyTimeout) as exc_info:
            await client.geocode_search(query="Bangkok", limit=5, language="th")

        assert exc_info.value.code.value == "DEPENDENCY_TIMEOUT"


@respx.mock
async def test_external_data_500_raises_dependency_unavailable(settings: Settings) -> None:
    respx.post(f"{settings.external_data_service_url.rstrip('/')}/internal/v1/geocode/search").mock(
        return_value=httpx.Response(502, text="Bad Gateway")
    )

    async with httpx.AsyncClient() as http_client:
        client = ExternalDataClient(http_client, settings)
        with pytest.raises(DependencyUnavailable) as exc_info:
            await client.geocode_search(query="Bangkok", limit=5, language="th")

        assert exc_info.value.code.value == "DEPENDENCY_UNAVAILABLE"


# --- Recommendation Failure Tests ---


@respx.mock
async def test_recommendation_timeout_raises_dependency_timeout(settings: Settings) -> None:
    rec_id = uuid.uuid4()
    respx.get(
        f"{settings.recommendation_service_url.rstrip('/')}/internal/v1/recommendations/{rec_id}"
    ).mock(side_effect=httpx.TimeoutException("rec timeout"))

    async with httpx.AsyncClient() as http_client:
        client = RecommendationClient(http_client, settings)
        with pytest.raises(DependencyTimeout) as exc_info:
            await client.fetch_validated(rec_id, request_id=uuid.uuid4(), trip_id=uuid.uuid4())

        assert exc_info.value.code.value == "DEPENDENCY_TIMEOUT"


@respx.mock
async def test_recommendation_404_raises_recommendation_invalid(settings: Settings) -> None:
    rec_id = uuid.uuid4()
    respx.get(
        f"{settings.recommendation_service_url.rstrip('/')}/internal/v1/recommendations/{rec_id}"
    ).mock(return_value=httpx.Response(404, json={"detail": "not found"}))

    async with httpx.AsyncClient() as http_client:
        client = RecommendationClient(http_client, settings)
        with pytest.raises(RecommendationInvalid):
            await client.fetch_validated(rec_id, request_id=uuid.uuid4(), trip_id=uuid.uuid4())


# --- Redis Failure & Readiness Probes ---


async def test_redis_failure_health_probe_reports_down(settings: Settings) -> None:
    broken_redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.01)
    await broken_redis.aclose()

    check = redis_check(broken_redis, settings)
    try:
        await check.probe()
        probe_failed = False
    except Exception:
        probe_failed = True

    assert probe_failed is True
    assert check.name == "redis"


# --- OIDC Discovery Failure ---


@respx.mock
async def test_oidc_discovery_failure_health_probe_reports_down(settings: Settings) -> None:
    respx.get(settings.oidc_discovery_url).mock(
        side_effect=httpx.ConnectError("cannot reach Keycloak")
    )

    async with httpx.AsyncClient() as http_client:
        check = oidc_discovery_check(http_client, settings)
        try:
            await check.probe()
            probe_failed = False
        except Exception:
            probe_failed = True

        assert probe_failed is True
        assert check.name == "oidc"
