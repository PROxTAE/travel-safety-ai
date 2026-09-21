"""Snapshot endpoints against real PostgreSQL with module 04 captures.

Records come from tests/fixtures/m04-*.json (Open-Meteo Bangkok, USGS and the
openrouteservice route, all HTTP 200 captures). The route line is a test-only
geometry on the captured Bangkok forecast coordinate.
"""

import json
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import make_url

from app.domain.snapshot import IntegratedTravelContext
from app.main import create_app
from app.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures"
LINE = [[100.495865, 13.743409], [100.505865, 13.743409]]


def record(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


def body(**changes: Any) -> dict[str, Any]:
    route = record("m04-route-candidates.json") | {
        "geometry": {"type": "LineString", "coordinates": LINE}
    }
    weather = record("m04-weather-forecast-points.json")
    quake = record("m04-usgs-event.json")
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


async def test_create_replay_read_and_validate(client: httpx.AsyncClient) -> None:
    payload = body()
    created = await client.post("/internal/v1/snapshots", json=payload)
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    snapshot = IntegratedTravelContext.model_validate(data)
    assert snapshot.features["max_wind_gust_kmh"] == 19.8
    assert snapshot.route_corridor_geojson.type in {"Polygon", "MultiPolygon"}
    assert "corridor_radius_m=5000" in snapshot.quality_summary.notes

    replay = await client.post("/internal/v1/snapshots", json=payload)
    assert replay.status_code == 200
    assert replay.json()["data"]["snapshot_id"] == data["snapshot_id"]

    read = await client.get(f"/internal/v1/snapshots/{data['snapshot_id']}")
    assert read.status_code == 200
    assert read.json()["data"] == data

    report = (await client.post(f"/internal/v1/snapshots/{data['snapshot_id']}/validate")).json()
    assert report["data"]["content_hash_matches"] is True
    assert report["data"]["schema_valid"] is True
    # Module 04 leaves completeness unknown, so the score is null and the gate DEGRADED.
    assert report["data"]["gate"] == "DEGRADED"
    assert report["data"]["valid"] is True
    strict = await client.post(
        f"/internal/v1/snapshots/{data['snapshot_id']}/validate", json={"strict": True}
    )
    assert strict.json()["data"]["valid"] is False


async def test_same_request_id_with_other_content_conflicts(client: httpx.AsyncClient) -> None:
    payload = body()
    assert (await client.post("/internal/v1/snapshots", json=payload)).status_code == 201
    changed = payload | {"recommendation_at": "2026-09-20T19:00:00Z"}
    conflict = await client.post("/internal/v1/snapshots", json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_unavailable_sources_block_and_stay_null(client: httpx.AsyncClient) -> None:
    payload = body(
        evidence={"weather": None, "disaster_events": None, "transport": None},
        source_quality={"route": record("m04-route-candidates.json")["quality"]},
    )
    created = await client.post("/internal/v1/snapshots", json=payload)
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["features"]["max_weather_severity_ordinal"] is None
    assert data["features"]["corridor_official_closure_active"] is None
    assert data["weather"] == [] and data["disaster_events"] == []
    assert "gate=BLOCK" in data["quality_summary"]["notes"]
    report = await client.post(f"/internal/v1/snapshots/{data['snapshot_id']}/validate")
    assert report.json()["data"]["valid"] is False
    assert report.json()["data"]["missing_critical"] == ["disaster", "weather"]


async def test_evidence_after_recommendation_stays_out_of_snapshot(
    client: httpx.AsyncClient,
) -> None:
    payload = body(recommendation_at="2026-09-20T17:00:00Z")
    data = (await client.post("/internal/v1/snapshots", json=payload)).json()["data"]
    # The forecast was fetched at 17:24, after the 17:00 recommendation.
    assert data["weather"] == []
    assert data["features"]["max_wind_gust_kmh"] is None


async def test_errors_use_the_contract_envelope(client: httpx.AsyncClient) -> None:
    missing = await client.get(f"/internal/v1/snapshots/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    superseded = await client.post(
        "/internal/v1/snapshots", json=body(supersedes_snapshot_id=str(uuid4()))
    )
    assert superseded.status_code == 404
    extra = await client.post("/internal/v1/snapshots", json=body(unexpected=True))
    assert extra.status_code == 422
    assert extra.json()["error"]["code"] == "VALIDATION_ERROR"
    assert {"path": "unexpected", "code": "UNKNOWN_FIELD"} in extra.json()["error"]["field_errors"]
    anonymous = await client.get(f"/internal/v1/snapshots/{uuid4()}", headers={"Authorization": ""})
    assert anonymous.status_code == 401
