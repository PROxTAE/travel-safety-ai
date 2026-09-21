"""Maintenance commands are idempotent against real PostgreSQL.

Records are module 04 captures from tests/fixtures/m04-*.json; the snapshot
request uses a test-only route line on the captured Bangkok forecast point.
"""

import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from prometheus_client import REGISTRY
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url

from app.cli.operations import backfill, purge_quarantine, rebuild
from app.main import create_app
from app.repositories.db import build_engine, build_session_factory, unit_of_work
from app.repositories.models import CanonicalRecord, Quarantine
from app.repositories.snapshot_repo import SnapshotRepository
from app.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures"


def record(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


def quarantined_metric() -> float:
    return (
        REGISTRY.get_sample_value("integration_quarantined_total", {"error_code": "INVALID_INPUT"})
        or 0.0
    )


async def test_backfill_twice_stores_once_and_quarantines_once(isolated_database: str) -> None:
    engine = build_engine(isolated_database)
    marker = secrets.token_hex(6)
    lines = [
        json.dumps(record("m04-weather-forecast-points.json")),
        json.dumps({"id": f"broken-{marker}"}),
    ]
    try:
        before = quarantined_metric()
        first = await backfill(engine, "weather", lines)
        second = await backfill(engine, "weather", lines)
        assert (first.stored, first.quarantined) == (1, 1)
        assert (second.stored, second.quarantined) == (1, 1)
        async with unit_of_work(build_session_factory(engine)) as session:
            source_id = record("m04-weather-forecast-points.json")["source"]["source_id"]
            rows = await session.scalar(
                select(func.count()).where(CanonicalRecord.source_id == source_id)
            )
            assert rows == 1
        # The invalid line was quarantined in the first run only.
        assert quarantined_metric() - before == 1
    finally:
        await engine.dispose()


async def test_purge_removes_only_expired_rows(isolated_database: str) -> None:
    engine = build_engine(isolated_database)
    old_hash, new_hash = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    try:
        async with unit_of_work(build_session_factory(engine)) as session:
            session.add_all(
                [
                    Quarantine(source_hash=old_hash, error_code="INVALID_INPUT"),
                    Quarantine(source_hash=new_hash, error_code="INVALID_INPUT"),
                ]
            )
            await session.flush()
            await session.execute(
                update(Quarantine)
                .where(Quarantine.source_hash == old_hash)
                .values(created_at=datetime.now(UTC) - timedelta(days=40))
            )
        assert await purge_quarantine(engine, 30) >= 1
        assert await purge_quarantine(engine, 30) == 0
        async with unit_of_work(build_session_factory(engine)) as session:
            left = await session.scalars(
                select(Quarantine.source_hash).where(
                    Quarantine.source_hash.in_([old_hash, new_hash])
                )
            )
            assert list(left) == [new_hash]
    finally:
        await engine.dispose()


async def test_rebuild_reproduces_and_detects_drift(
    isolated_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTGRES_DB", make_url(isolated_database).database or "")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", secrets.token_urlsafe(32))
    get_settings.cache_clear()
    route = record("m04-route-candidates.json") | {
        "geometry": {
            "type": "LineString",
            "coordinates": [[100.495865, 13.743409], [100.505865, 13.743409]],
        }
    }
    weather, quake = record("m04-weather-forecast-points.json"), record("m04-usgs-event.json")
    body = {
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
        "source_quality": {"route": route["quality"], "weather": weather["quality"]},
    }
    app = create_app()
    token = get_settings().internal_service_token
    assert token is not None
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
        ) as client:
            created = await client.post("/internal/v1/snapshots", json=body)
    snapshot_id = created.json()["data"]["snapshot_id"]
    engine = build_engine(isolated_database)
    try:
        settings = get_settings()
        assert await rebuild(engine, snapshot_id, settings) == "reproducible"
        wider = settings.model_copy(update={"corridor_radius_m": settings.corridor_radius_m * 2})
        assert await rebuild(engine, snapshot_id, wider) == "drift"
        assert await rebuild(engine, uuid4(), settings) == "missing"
        async with unit_of_work(build_session_factory(engine)) as session:
            legacy = await SnapshotRepository(session).create(
                request_id=uuid4(),
                input_content_hash="sha256:" + "3" * 64,
                schema_version="1.0.0",
                evidence={"source_ids": ["stored-before-0006"]},
            )
            legacy_id = legacy.id
        assert await rebuild(engine, legacy_id, settings) == "not_rebuildable"
    finally:
        await engine.dispose()
        get_settings.cache_clear()
