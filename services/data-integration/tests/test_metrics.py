"""Pipeline metrics move exactly once per stored snapshot, replay or rejection.

Requests use module 04 captures from tests/fixtures/m04-*.json with a test-only
route line on the captured Bangkok forecast point.
"""

import json
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from prometheus_client import REGISTRY
from sqlalchemy.engine import make_url

from app.main import create_app
from app.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures"


def record(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


def body(**changes: Any) -> dict[str, Any]:
    route = record("m04-route-candidates.json") | {
        "geometry": {
            "type": "LineString",
            "coordinates": [[100.495865, 13.743409], [100.505865, 13.743409]],
        }
    }
    weather, quake = record("m04-weather-forecast-points.json"), record("m04-usgs-event.json")
    payload = {
        "request_id": str(uuid4()),
        "trip_id": str(uuid4()),
        "travel_window": {
            "starts_at": "2026-09-19T00:00:00Z",
            "ends_at": "2026-09-19T01:00:00Z",
            "timezone": "Asia/Bangkok",
        },
        "recommendation_at": "2026-09-20T18:00:00Z",
        "route": route,
        "evidence": {"weather": [weather], "disaster_events": [quake], "transport": []},
        "source_quality": {
            "route": route["quality"],
            "weather": weather["quality"],
            "disaster": quake["quality"],
        },
    }
    return payload | changes


def sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


@pytest.fixture
async def client(
    isolated_database: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("POSTGRES_DB", make_url(isolated_database).database or "")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", secrets.token_urlsafe(32))
    get_settings.cache_clear()
    app = create_app()
    token = get_settings().internal_service_token
    assert token is not None
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
        ) as http:
            yield http
    get_settings.cache_clear()


async def test_stored_snapshot_and_replay_are_counted_once(client: httpx.AsyncClient) -> None:
    created = ("integration_snapshots_created_total", {"gate": "DEGRADED"})
    builds = "integration_snapshot_build_seconds_count"
    replays = "integration_snapshot_replays_total"
    coverage = "integration_evidence_coverage_ratio_count"
    before = (sample(*created), sample(builds), sample(replays), sample(coverage))
    payload = body()
    assert (await client.post("/internal/v1/snapshots", json=payload)).status_code == 201
    assert (await client.post("/internal/v1/snapshots", json=payload)).status_code == 200
    after = (sample(*created), sample(builds), sample(replays), sample(coverage))
    assert [b - a for a, b in zip(before, after, strict=True)] == [1, 1, 1, 1]


async def test_unavailable_sources_count_block_and_unknown_age(client: httpx.AsyncClient) -> None:
    blocked = ("integration_snapshots_created_total", {"gate": "BLOCK"})
    unknown_age = "integration_evidence_age_unknown_total"
    missing_flag = ("integration_quality_flags_total", {"flag": "MISSING"})
    before = (sample(*blocked), sample(unknown_age), sample(*missing_flag))
    payload = body(
        evidence={"weather": None, "disaster_events": None, "transport": None},
        source_quality={"route": record("m04-route-candidates.json")["quality"]},
    )
    assert (await client.post("/internal/v1/snapshots", json=payload)).status_code == 201
    after = (sample(*blocked), sample(unknown_age), sample(*missing_flag))
    assert [b - a for a, b in zip(before, after, strict=True)] == [1, 1, 1]


async def test_rejected_request_is_counted_by_code_and_exposed(client: httpx.AsyncClient) -> None:
    rejected = ("integration_requests_rejected_total", {"code": "UNKNOWN_FIELD"})
    before = sample(*rejected)
    response = await client.post("/internal/v1/snapshots", json=body(unexpected=True))
    assert response.status_code == 422
    assert sample(*rejected) - before == 1
    exposed = (await client.get("/metrics")).text
    for name in (
        "integration_snapshots_created_total",
        "integration_snapshot_build_seconds",
        "integration_quality_flags_total",
        "integration_evidence_conflicts_total",
        "integration_evidence_freshness_seconds",
        "integration_requests_rejected_total",
        "integration_quarantined_total",
    ):
        assert name in exposed
