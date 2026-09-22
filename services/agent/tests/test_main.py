"""End-to-end tests through the real FastAPI app, with no PostgreSQL/Redis configured — exercises
exactly what a developer machine or a container without those dependencies wired up yet can prove:
health, readiness, metrics, and the full synchronous run lifecycle (Phase 1 has no worker, so
`POST /internal/v1/runs` runs the graph to completion within the request; see
app/api/internal.py's module docstring).

Tests that need real PostgreSQL/Redis (`get`/`resume`/`cancel`, which persist to `agent.runs`, and
the Redis publisher) are `integration`-marked in tests/integration/ instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _location(confirmed: bool = True) -> dict[str, object]:
    return {
        "place_id": "p1",
        "display_name": "Bangkok",
        "coordinates": {"type": "Point", "coordinates": [100.5018, 13.7563]},
        "country_code": "TH",
        "timezone": "Asia/Bangkok",
        "provider": "test",
        "confirmed_by_user": confirmed,
    }


def _create_run_payload(*, confirmed: bool = True) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "travel_request": {
            "request_id": str(uuid.uuid4()),
            "trip_id": str(uuid.uuid4()),
            "origin": _location(confirmed),
            "destination": _location(confirmed),
            "departure_time": (now + timedelta(hours=1)).isoformat(),
            "travel_modes": ["TRAIN"],
            "locale": "th-TH",
            "timezone": "Asia/Bangkok",
        },
        "correlation_id": str(uuid.uuid4()),
        "user_scope_hash": "hash-only",
    }


def test_health_live(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_ready_without_database_or_redis_is_still_ready_in_development(
    client: TestClient,
) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ready"
    assert body["redis"] == "ready"


def test_metrics_endpoint_serves_prometheus_text(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_create_run_with_confirmed_locations_fails_honestly_not_a_fake_completion(
    client: TestClient,
) -> None:
    response = client.post("/internal/v1/runs", json=_create_run_payload(confirmed=True))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"


def test_create_run_with_unconfirmed_locations_asks_for_input(client: TestClient) -> None:
    response = client.post("/internal/v1/runs", json=_create_run_payload(confirmed=False))
    assert response.status_code == 200
    assert response.json()["status"] == "NEEDS_INPUT"


def test_create_run_rejects_an_unknown_field(client: TestClient) -> None:
    payload = _create_run_payload()
    payload["not_a_real_field"] = "x"
    response = client.post("/internal/v1/runs", json=payload)
    assert response.status_code == 422


def test_get_run_without_storage_configured_is_503_not_a_guess(client: TestClient) -> None:
    response = client.get(f"/internal/v1/runs/{uuid.uuid4()}")
    assert response.status_code == 503


def test_resume_without_storage_configured_is_503(client: TestClient) -> None:
    response = client.post(
        f"/internal/v1/runs/{uuid.uuid4()}/resume",
        json={"user_scope_hash": "h", "confirmed_origin": True, "confirmed_destination": True},
    )
    assert response.status_code == 503


def test_cancel_without_storage_configured_is_503(client: TestClient) -> None:
    response = client.post(f"/internal/v1/runs/{uuid.uuid4()}/cancel", json={})
    assert response.status_code == 503
