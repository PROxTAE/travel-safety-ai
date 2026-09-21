"""Phase 7 scenarios: late event, provider update, duplicate, official vs community conflict.

Every event starts from the captured module 04 USGS record
(tests/fixtures/m04-usgs-event.json, HTTP 200). Each scenario changes only the
fields it is about (authority, severity, geometry, times, ids), and says so.
The route is a test-only line on the captured Bangkok forecast coordinate.
"""

import json
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.cli.operations import backfill
from app.main import create_app
from app.repositories.db import build_engine, build_session_factory, unit_of_work
from app.repositories.models import CanonicalRecord
from app.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures"
LINE = [[100.495865, 13.743409], [100.505865, 13.743409]]
AREA = {
    "type": "Polygon",
    "coordinates": [
        [[100.49, 13.73], [100.51, 13.73], [100.51, 13.76], [100.49, 13.76], [100.49, 13.73]]
    ],
}


def record(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


def event(source_id: str, **changes: Any) -> dict[str, Any]:
    """The captured USGS event, moved onto the route and re-sourced for one scenario."""
    base = record("m04-usgs-event.json")
    source = base["source"] | {"source_id": source_id} | changes.pop("source", {})
    return (
        base
        | {
            "event_id": source_id,
            "geometry": AREA,
            "effective_at": "2026-09-18T00:00:00Z",
            "source": source,
        }
        | changes
    )


def request(**changes: Any) -> dict[str, Any]:
    route = record("m04-route-candidates.json") | {
        "geometry": {"type": "LineString", "coordinates": LINE}
    }
    weather = record("m04-weather-forecast-points.json")
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
        "evidence": {"weather": [weather], "disaster_events": [], "transport": []},
        "source_quality": {
            "route": route["quality"],
            "weather": weather["quality"],
            "disaster": record("m04-usgs-event.json")["quality"],
        },
    }
    return body | changes


def evidence(disasters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "weather": [record("m04-weather-forecast-points.json")],
        "disaster_events": disasters,
        "transport": [],
    }


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


async def test_late_official_event_refreshes_without_touching_the_first_snapshot(
    client: httpx.AsyncClient,
) -> None:
    first = (await client.post("/internal/v1/snapshots", json=request())).json()["data"]
    assert first["features"]["corridor_extreme_alert_active"] is False
    # Variant: an official EXTREME closure issued over the route after the first recommendation.
    late = event(
        "test:late-official",
        severity="EXTREME",
        official=True,
        event_type="TRANSPORT_CLOSURE",
        source={"authority": "OFFICIAL", "fetched_at": "2026-09-20T19:00:00Z"},
    )
    too_early = request(recommendation_at="2026-09-20T18:30:00Z", evidence=evidence([late]))
    early = (await client.post("/internal/v1/snapshots", json=too_early)).json()["data"]
    assert early["disaster_events"] == []  # not known yet at 18:30
    refresh = request(
        recommendation_at="2026-09-20T19:30:00Z",
        evidence=evidence([late]),
        supersedes_snapshot_id=first["snapshot_id"],
    )
    second = (await client.post("/internal/v1/snapshots", json=refresh)).json()["data"]
    assert second["supersedes_snapshot_id"] == first["snapshot_id"]
    assert second["features"]["corridor_extreme_alert_active"] is True
    assert second["features"]["corridor_official_closure_active"] is True
    assert second["features"]["hazard_intersection_fraction"] > 0
    assert [e["event_id"] for e in second["official_alerts"]] == ["test:late-official"]
    stored_first = (await client.get(f"/internal/v1/snapshots/{first['snapshot_id']}")).json()
    assert stored_first["data"] == first


async def test_provider_update_keeps_both_versions(isolated_database: str) -> None:
    # Variant: the same provider record published twice with a raised severity.
    original = event("usgs:scenario-update", severity="MODERATE")
    updated = event(
        "usgs:scenario-update",
        severity="SEVERE",
        source={"fetched_at": "2026-09-20T19:00:00Z"},
    )
    engine = build_engine(isolated_database)
    try:
        lines = [json.dumps(original), json.dumps(updated)]
        report = await backfill(engine, "disaster", lines)
        again = await backfill(engine, "disaster", lines)
        assert (report.stored, again.stored) == (2, 2)
        async with unit_of_work(build_session_factory(engine)) as session:
            versions = await session.scalar(
                select(func.count()).where(CanonicalRecord.source_id == "usgs:scenario-update")
            )
        assert versions == 2
    finally:
        await engine.dispose()


async def test_duplicate_sources_agree_and_measure_agreement(client: httpx.AsyncClient) -> None:
    # Variant: one event reported by USGS and cross-referenced by an intergovernmental source.
    usgs = event("usgs:scenario-dup", severity="SEVERE", official=True)
    other = event(
        "gdacs:scenario-dup",
        severity="SEVERE",
        official=True,
        cross_reference_ids=["usgs:scenario-dup"],
        source={"provider": "gdacs", "authority": "INTERGOVERNMENTAL"},
    )
    body = request(evidence=evidence([usgs, other]))
    data = (await client.post("/internal/v1/snapshots", json=body)).json()["data"]
    assert data["conflict_summary"] == []
    assert "CONFLICTING" not in data["quality_summary"]["flags"]
    assert len(data["disaster_events"]) == 2  # both sources kept as evidence


async def test_official_and_community_conflict_is_kept_not_averaged(
    client: httpx.AsyncClient,
) -> None:
    # Variant: an official EXTREME warning and a community MINOR report of the same event.
    official = event("official:scenario-conflict", severity="EXTREME", official=True,
                     source={"authority": "OFFICIAL"})  # fmt: skip
    community = event(
        "community:scenario-conflict",
        severity="MINOR",
        official=False,
        cross_reference_ids=["official:scenario-conflict"],
        source={"provider": "community", "authority": "COMMUNITY"},
    )
    body = request(evidence=evidence([official, community]))
    data = (await client.post("/internal/v1/snapshots", json=body)).json()["data"]
    assert len(data["conflict_summary"]) == 1
    conflict = data["conflict_summary"][0]
    assert conflict["resolution"] == "UNRESOLVED"
    assert sorted(conflict["source_ids"]) == [
        "community:scenario-conflict",
        "official:scenario-conflict",
    ]
    # The official EXTREME warning is not weakened by the community report.
    assert data["features"]["corridor_extreme_alert_active"] is True
    assert data["quality_summary"]["status"] == "CONFLICTING"
    assert "gate=DEGRADED" in data["quality_summary"]["notes"]
    report = await client.post(f"/internal/v1/snapshots/{data['snapshot_id']}/validate")
    assert "CONFLICTING" in report.json()["data"]["flags"]
