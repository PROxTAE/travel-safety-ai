"""Contract tests for app/tools/clients/ — valid/malformed response, timeout, retryable vs
non-retryable errors, auth, and required headers — mocking the httpx transport (respx), never
business data. No real data-integration/risk-knowledge instance is needed or contacted.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.settings import Settings
from app.tools.clients.base import ToolCallError
from app.tools.clients.data_integration import DataIntegrationClient
from app.tools.clients.risk_knowledge import RiskKnowledgeClient
from app.tools.schemas import (
    EvidencePackageRequest,
    SnapshotCreateRequest,
    SnapshotEvidence,
    TravelWindow,
)

_BASE_URL = "http://data-integration:8003"
_RK_BASE_URL = "http://risk-knowledge:8004"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _snapshot_request() -> SnapshotCreateRequest:
    return SnapshotCreateRequest(
        request_id=uuid.uuid4(),
        trip_id=uuid.uuid4(),
        travel_window=TravelWindow(
            starts_at="2026-09-20T09:00:00Z",  # type: ignore[arg-type]
            ends_at="2026-09-20T12:00:00Z",  # type: ignore[arg-type]
            timezone="Asia/Bangkok",
        ),
        recommendation_at="2026-09-20T08:30:00Z",  # type: ignore[arg-type]
        route={  # type: ignore[arg-type]
            "route_id": str(uuid.uuid4()),
            "provider_route_id": "p1",
            "label": "ORIGINAL",
            "mode": "TRAIN",
            "geometry": {"type": "LineString", "coordinates": [[100.5, 13.7], [100.6, 13.8]]},
            "segments": [],
            "distance_m": 1000,
            "duration_seconds": 600,
            "transfers": 0,
            "exposure": None,
            "risk_level": "UNKNOWN",
            "quality": {"status": "FRESH"},
            "sources": [],
        },
        evidence=SnapshotEvidence(weather=None, disaster_events=None, transport=None),
        source_quality={},
    )


def _valid_snapshot_response_json(request: SnapshotCreateRequest) -> dict[str, object]:
    return {
        "data": {
            "snapshot_id": str(uuid.uuid4()),
            "request_id": str(request.request_id),
            "trip_id": str(request.trip_id),
            "schema_version": "1.0.0",
            "content_hash": "sha256:" + "0" * 64,
            "quality_summary": {"status": "FRESH"},
            "created_at": "2026-09-20T08:31:00Z",
        },
        "meta": {
            "request_id": str(request.request_id),
            "contract_version": "1.0.0",
            "generated_at": "2026-09-20T08:31:00Z",
        },
    }


def _error_json(code: str, retryable: bool) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": "safe message",
            "field_errors": [],
            "retryable": retryable,
            "retry_after_seconds": None,
        },
        "meta": {
            "request_id": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4()),
            "contract_version": "1.0.0",
            "generated_at": "2026-09-20T08:31:00Z",
            "degraded_services": [],
        },
    }


class TestDataIntegrationClient:
    @respx.mock
    async def test_parses_a_valid_response(self) -> None:
        request = _snapshot_request()
        route = respx.post(f"{_BASE_URL}/internal/v1/snapshots").mock(
            return_value=httpx.Response(201, json=_valid_snapshot_response_json(request))
        )
        client = DataIntegrationClient(_settings())
        try:
            response, record = await client.create_snapshot(
                request,
                correlation_id=uuid.uuid4(),
                traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            )
        finally:
            await client.aclose()

        assert response.data.request_id == request.request_id
        assert record.status == "success"
        assert record.tool_name == "data_integration.create_snapshot@1"
        assert route.called
        sent_headers = route.calls.last.request.headers
        assert sent_headers["X-Request-ID"] == str(request.request_id)
        assert sent_headers["X-Contract-Version"] == "1"
        assert "Idempotency-Key" not in sent_headers

    @respx.mock
    async def test_sends_the_bearer_token_when_configured(self) -> None:
        request = _snapshot_request()
        route = respx.post(f"{_BASE_URL}/internal/v1/snapshots").mock(
            return_value=httpx.Response(201, json=_valid_snapshot_response_json(request))
        )
        client = DataIntegrationClient(_settings(internal_service_token=SecretStr("x" * 16)))
        try:
            await client.create_snapshot(
                request,
                correlation_id=uuid.uuid4(),
                traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            )
        finally:
            await client.aclose()

        assert route.calls.last.request.headers["Authorization"] == "Bearer " + "x" * 16

    @respx.mock
    async def test_malformed_response_becomes_internal_error(self) -> None:
        request = _snapshot_request()
        respx.post(f"{_BASE_URL}/internal/v1/snapshots").mock(
            return_value=httpx.Response(201, json={"data": {"snapshot_id": "not-a-uuid"}})
        )
        client = DataIntegrationClient(_settings())
        try:
            with pytest.raises(ToolCallError) as excinfo:
                await client.create_snapshot(
                    request,
                    correlation_id=uuid.uuid4(),
                    traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
                )
        finally:
            await client.aclose()
        assert excinfo.value.error_code == "INTERNAL_ERROR"
        assert excinfo.value.retryable is False
        assert excinfo.value.record is not None
        assert excinfo.value.record.status == "failed"

    @respx.mock
    async def test_401_is_not_retried(self) -> None:
        request = _snapshot_request()
        route = respx.post(f"{_BASE_URL}/internal/v1/snapshots").mock(
            return_value=httpx.Response(401, json=_error_json("AUTHENTICATION_REQUIRED", False))
        )
        client = DataIntegrationClient(_settings())
        try:
            with pytest.raises(ToolCallError) as excinfo:
                await client.create_snapshot(
                    request,
                    correlation_id=uuid.uuid4(),
                    traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
                )
        finally:
            await client.aclose()
        assert excinfo.value.error_code == "AUTHENTICATION_REQUIRED"
        assert excinfo.value.retryable is False
        assert route.call_count == 1

    @respx.mock
    async def test_dependency_unavailable_is_retried_up_to_max_attempts(self) -> None:
        request = _snapshot_request()
        route = respx.post(f"{_BASE_URL}/internal/v1/snapshots").mock(
            return_value=httpx.Response(503, json=_error_json("DEPENDENCY_UNAVAILABLE", True))
        )
        client = DataIntegrationClient(_settings())
        try:
            with pytest.raises(ToolCallError) as excinfo:
                await client.create_snapshot(
                    request,
                    correlation_id=uuid.uuid4(),
                    traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
                )
        finally:
            await client.aclose()
        assert excinfo.value.error_code == "DEPENDENCY_UNAVAILABLE"
        # max_attempts=2 for this tool (app/tools/registry.py) — one original try + one retry.
        assert route.call_count == 2

    @respx.mock
    async def test_timeout_is_retried_then_reported_as_dependency_timeout(self) -> None:
        request = _snapshot_request()
        route = respx.post(f"{_BASE_URL}/internal/v1/snapshots").mock(
            side_effect=httpx.ConnectTimeout("connect timed out")
        )
        client = DataIntegrationClient(_settings())
        try:
            with pytest.raises(ToolCallError) as excinfo:
                await client.create_snapshot(
                    request,
                    correlation_id=uuid.uuid4(),
                    traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
                )
        finally:
            await client.aclose()
        assert excinfo.value.error_code == "DEPENDENCY_TIMEOUT"
        assert route.call_count == 2


class TestRiskKnowledgeClient:
    @respx.mock
    async def test_not_idempotent_sends_no_idempotency_key(self) -> None:
        snapshot_id = uuid.uuid4()
        route = respx.post(f"{_RK_BASE_URL}/internal/v1/evidence/package").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "snapshot_id": str(snapshot_id),
                        "assessments": [],
                        "evidence": [],
                        "routes": [],
                        "capabilities": [],
                        "limitations": [],
                        "versions": {
                            "contract": "1.0.0",
                            "feature_schema": "1.0.0",
                            "route_policy": "1.0.0",
                        },
                    },
                    "meta": {
                        "request_id": str(uuid.uuid4()),
                        "correlation_id": str(uuid.uuid4()),
                        "contract_version": "1.0.0",
                        "generated_at": "2026-09-20T08:31:00Z",
                        "degraded_services": [],
                    },
                },
            )
        )
        client = RiskKnowledgeClient(_settings())
        try:
            response, record = await client.build_evidence_package(
                EvidencePackageRequest(snapshot_id=snapshot_id, locale="en-US"),
                request_id=uuid.uuid4(),
                correlation_id=uuid.uuid4(),
                traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            )
        finally:
            await client.aclose()

        assert response.data.snapshot_id == snapshot_id
        assert record.status == "success"
        assert "Idempotency-Key" not in route.calls.last.request.headers

    @respx.mock
    async def test_rate_limited_is_retryable(self) -> None:
        route = respx.post(f"{_RK_BASE_URL}/internal/v1/evidence/package").mock(
            return_value=httpx.Response(429, json=_error_json("RATE_LIMITED", True))
        )
        client = RiskKnowledgeClient(_settings())
        try:
            with pytest.raises(ToolCallError) as excinfo:
                await client.build_evidence_package(
                    EvidencePackageRequest(snapshot_id=uuid.uuid4(), locale="en-US"),
                    request_id=uuid.uuid4(),
                    correlation_id=uuid.uuid4(),
                    traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
                )
        finally:
            await client.aclose()
        assert excinfo.value.error_code == "RATE_LIMITED"
        assert route.call_count == 2
