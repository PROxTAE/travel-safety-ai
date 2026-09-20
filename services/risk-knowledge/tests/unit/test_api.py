from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.context import RequestContextMiddleware
from app.errors import install_error_handlers
from app.runtime import KnowledgeRuntimeStatus, ModelRuntimeStatus
from app.settings import Settings

SERVICE_TOKEN = "test-only-internal-token"  # noqa: S105 - deterministic test credential
HEADERS = {
    "Authorization": f"Bearer {SERVICE_TOKEN}",
    "X-Request-ID": "50000000-0000-4000-8000-000000000001",
    "X-Correlation-ID": "50000000-0000-4000-8000-000000000002",
    "X-Contract-Version": "1",
    "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
}


class FakeSession:
    pass


class FakeSessions:
    @asynccontextmanager
    async def __call__(self):  # type: ignore[no-untyped-def]
        yield FakeSession()


@dataclass
class FakeDatabase:
    ready: bool = True
    detail: str | None = None
    sessions: Any = None

    def __post_init__(self) -> None:
        if self.sessions is None:
            self.sessions = FakeSessions()

    async def check_ready(self) -> tuple[bool, str | None]:
        return self.ready, self.detail


class FakeRuntime:
    def __init__(self, *, database_ready: bool = True) -> None:
        self.database = FakeDatabase(database_ready, None if database_ready else "down")
        self.model = ModelRuntimeStatus("UNAVAILABLE", "NO_APPROVED_ACTIVE_MODEL", None)
        self.knowledge = KnowledgeRuntimeStatus(
            "UNAVAILABLE", "NO_ACTIVE_KNOWLEDGE_COLLECTION", None, None
        )

    async def refresh_model(self) -> ModelRuntimeStatus:
        return self.model

    async def refresh_knowledge(self) -> KnowledgeRuntimeStatus:
        return self.knowledge


def make_client(
    *, runtime: FakeRuntime | None = None, token: str | None = SERVICE_TOKEN
) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(
        APP_ENV="test",
        INTERNAL_SERVICE_TOKEN=token,
        RISK_KNOWLEDGE_DEPENDENCY_TIMEOUT_SECONDS=0.2,
    )
    app.state.runtime = runtime or FakeRuntime()
    app.state.json_dumps = lambda value: json.dumps(value, default=str)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(internal_router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def successful_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.api.internal.save_fallback_assessments", noop)
    monkeypatch.setattr("app.api.internal.save_fallback_route_evaluations", noop)


def test_health_readiness_and_metrics_expose_degraded_state() -> None:
    client = make_client()
    assert client.get("/health/live").json()["status"] == "ok"
    readiness = client.get("/health/ready")
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "degraded"
    assert client.get("/metrics").status_code == 200


def test_readiness_fails_when_critical_database_is_down() -> None:
    response = make_client(runtime=FakeRuntime(database_ready=False)).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_readiness_fails_when_internal_auth_is_unconfigured() -> None:
    response = make_client(token=None).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["components"]["internal_auth"]["status"] == "UNAVAILABLE"


def test_internal_fallback_endpoints_are_explicit_and_persisted(
    snapshot_payload: dict[str, Any], successful_persistence: None
) -> None:
    client = make_client()
    route_id = snapshot_payload["route_candidates"][0]["route_id"]

    risk = client.post(
        "/internal/v1/risk/assess",
        headers=HEADERS,
        json={"snapshot": snapshot_payload, "route_ids": [route_id]},
    )
    assert risk.status_code == 200
    assert risk.json()["data"]["capability"]["status"] == "DEGRADED"
    assert risk.json()["data"]["assessments"][0]["risk_level"] == "UNKNOWN"

    knowledge = client.post(
        "/internal/v1/knowledge/retrieve",
        headers=HEADERS,
        json={
            "hazards": ["EARTHQUAKE"],
            "country_codes": ["US"],
            "action_code": "NORMAL",
            "locale": "en-US",
            "at": datetime.now(UTC).isoformat(),
        },
    )
    assert knowledge.status_code == 200
    assert knowledge.json()["data"]["evidence"] == []
    assert knowledge.json()["data"]["capability"]["status"] == "UNAVAILABLE"

    routes = client.post(
        "/internal/v1/routes/evaluate",
        headers=HEADERS,
        json={
            "snapshot": snapshot_payload,
            "route_ids": [route_id],
            "avoid_geometries": [],
            "preferences": {},
        },
    )
    assert routes.status_code == 200
    assert routes.json()["data"]["capability"]["status"] == "DEGRADED"
    assert len(routes.json()["data"]["routes"]) == 1


@pytest.mark.parametrize(
    ("path", "extra_payload"),
    [
        ("/internal/v1/risk/assess", {}),
        (
            "/internal/v1/routes/evaluate",
            {"avoid_geometries": [], "preferences": {}},
        ),
    ],
)
def test_route_selection_rejects_unknown_and_duplicate_ids(
    snapshot_payload: dict[str, Any], path: str, extra_payload: dict[str, Any]
) -> None:
    client = make_client()
    existing_route_id = snapshot_payload["route_candidates"][0]["route_id"]
    invalid_route_selections = [
        ["60000000-0000-4000-8000-000000000099"],
        [existing_route_id, existing_route_id],
    ]

    for route_ids in invalid_route_selections:
        response = client.post(
            path,
            headers=HEADERS,
            json={
                "snapshot": snapshot_payload,
                "route_ids": route_ids,
                **extra_payload,
            },
        )

        assert response.status_code == 422
        assert response.headers["X-Error-Code"] == "VALIDATION_ERROR"
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_status_evidence_and_error_contracts(snapshot_payload: dict[str, Any]) -> None:
    client = make_client()
    assert client.get("/internal/v1/models/current", headers=HEADERS).status_code == 200
    assert client.get("/internal/v1/knowledge/status", headers=HEADERS).status_code == 200

    evidence = client.post(
        "/internal/v1/evidence/package",
        headers=HEADERS,
        json={"snapshot_id": snapshot_payload["snapshot_id"], "locale": "en-US"},
    )
    assert evidence.status_code == 503
    assert evidence.headers["X-Error-Code"] == "DEPENDENCY_UNAVAILABLE"
    assert evidence.json()["error"]["retryable"] is False

    unauthorized = client.get("/internal/v1/models/current")
    assert unauthorized.status_code == 401
    assert unauthorized.headers["X-Error-Code"] == "AUTHENTICATION_REQUIRED"

    invalid = client.post(
        "/internal/v1/knowledge/retrieve",
        headers=HEADERS,
        json={"hazards": [], "country_codes": [], "action_code": "NORMAL", "locale": "bad"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_route_returns_standard_error_envelope() -> None:
    response = make_client().get("/internal/v1/does-not-exist", headers=HEADERS)

    assert response.status_code == 404
    assert response.headers["X-Error-Code"] == "NOT_FOUND"
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "Not Found",
        "field_errors": [],
        "retryable": False,
        "retry_after_seconds": None,
    }
    assert response.json()["meta"]["contract_version"] == "1.0.0"


def test_persistence_unavailable_and_failure_return_retryable_503(
    snapshot_payload: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = FakeRuntime()
    runtime.database.sessions = None
    route_id = snapshot_payload["route_candidates"][0]["route_id"]
    response = make_client(runtime=runtime).post(
        "/internal/v1/risk/assess",
        headers=HEADERS,
        json={"snapshot": snapshot_payload, "route_ids": [route_id]},
    )
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"

    async def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("test persistence failure")

    runtime = FakeRuntime()
    monkeypatch.setattr("app.api.internal.save_fallback_route_evaluations", fail)
    response = make_client(runtime=runtime).post(
        "/internal/v1/routes/evaluate",
        headers=HEADERS,
        json={
            "snapshot": snapshot_payload,
            "route_ids": [route_id],
            "avoid_geometries": [],
            "preferences": {},
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
