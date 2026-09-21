"""Snapshot assembly and persistence built from module 04 captures.

Records come from tests/fixtures/m04-*.json (Open-Meteo Bangkok, USGS, and the
openrouteservice route, all HTTP 200 captures). Route lines are test-only
geometries on captured coordinates; the Fiji line uses the captured Open-Meteo
dateline pair coordinates.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.canonical import (
    DisasterEvent,
    GeoLineString,
    QualityConflict,
    RouteCandidate,
    WeatherForecastPoint,
)
from app.domain.errors import SnapshotConflictError, SnapshotNotFoundError
from app.domain.snapshot import IntegratedTravelContext, TravelWindow
from app.pipeline.corridor import sample_route
from app.pipeline.features import FeatureInputs, FeaturePolicy, build_features
from app.pipeline.quality import QualityDimensions, QualityPolicy, summarize_quality
from app.pipeline.snapshot import assemble_snapshot, quality_status
from app.pipeline.spatial import corridor_buffer_geojson
from app.repositories.db import build_engine, build_session_factory, unit_of_work
from app.repositories.snapshot_repo import SnapshotRepository

FIXTURES = Path(__file__).parent / "fixtures"
DEPARTURE = datetime(2026, 9, 19, tzinfo=UTC)
LINE = [(100.495865, 13.743409), (100.505865, 13.743409)]
SQUARE = [(100.49, 13.73), (100.51, 13.73), (100.51, 13.75), (100.49, 13.75), (100.49, 13.73)]


def record(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


def snapshot(
    *,
    snapshot_id: UUID | None = None,
    request_id: UUID | None = None,
    created_at: datetime = datetime(2026, 9, 20, 18, tzinfo=UTC),
    supersedes: UUID | None = None,
    official: bool = True,
    gate_sources: bool = True,
) -> IntegratedTravelContext:
    base = RouteCandidate.model_validate(record("m04-route-candidates.json"))
    route = base.model_copy(update={"geometry": GeoLineString(type="LineString", coordinates=LINE)})
    samples = sample_route(route.geometry, departure_at=DEPARTURE, duration_seconds=3600,
                           max_spacing_m=1000)  # fmt: skip
    weather = [WeatherForecastPoint.model_validate(record("m04-weather-forecast-points.json"))]
    quake = DisasterEvent.model_validate(record("m04-usgs-event.json") | {"official": official})
    sources = {"route": route.quality, "weather": weather[0].quality} if gate_sources else {}
    features = build_features(
        FeatureInputs(
            route,
            samples,
            created_at,
            weather,
            [quake],
            None,
            sources,
            {
                "weather": weather[0].source.fetched_at,
                "disaster": quake.source.fetched_at,
            },
        ),
        FeaturePolicy(2000, 1200, 300),
    )
    quality = summarize_quality(
        sources,
        required=frozenset({"route", "weather"}),
        dimensions=QualityDimensions(1.0, None, 1 / 3, None, 0.7),
        policy=QualityPolicy("review-1", 0.8, 0.85),
        identity_valid=True,
        geometry_valid=True,
    )
    return assemble_snapshot(
        snapshot_id=snapshot_id or uuid4(),
        request_id=request_id or UUID("7d3c5f0e-3a57-4f2c-9a52-3d1f0b2e6c11"),
        trip_id=UUID("0f7c1c3e-5f3a-4a55-8c1d-8d9b1f7e2a10"),
        supersedes_snapshot_id=supersedes,
        travel_window=TravelWindow(
            starts_at=DEPARTURE, ends_at=samples[-1].eta, timezone="Asia/Bangkok"
        ),  # fmt: skip
        route=route,
        corridor={"type": "Polygon", "coordinates": [SQUARE]},
        corridor_radius_m=1000,
        weather=weather,
        transport=[],
        disasters=[quake],
        features=features,
        quality=quality,
        conflicts=[],
        created_at=created_at,
    )


def test_snapshot_carries_contract_fields_and_one_route() -> None:
    snap = snapshot()
    assert snap.schema_version == "1.0.0"
    assert snap.feature_schema_version == "1.0.0"
    assert len(snap.route_candidates) == 1
    assert snap.features["max_wind_gust_kmh"] == 19.8
    assert snap.official_alerts == snap.disaster_events
    assert snap.source_ids == sorted(set(snap.source_ids))
    assert snap.content_hash.startswith("sha256:")


def test_content_hash_ignores_identity_and_time_but_not_content() -> None:
    first = snapshot(snapshot_id=uuid4(), created_at=datetime(2026, 9, 20, 18, tzinfo=UTC))
    replay = snapshot(snapshot_id=uuid4(), created_at=datetime(2026, 9, 20, 19, tzinfo=UTC))
    assert first.content_hash == replay.content_hash
    changed = snapshot(official=False)
    assert changed.content_hash != first.content_hash
    assert changed.official_alerts == []


def test_unknown_dimensions_never_report_fresh() -> None:
    snap = snapshot()
    assert snap.quality_summary.score is None
    assert snap.quality_summary.status == "PARTIAL"
    assert "gate=DEGRADED" in snap.quality_summary.notes
    assert "INCOMPLETE" in snap.quality_summary.flags


def test_missing_critical_source_is_partial_with_named_gap() -> None:
    snap = snapshot(gate_sources=False)
    assert "gate=BLOCK" in snap.quality_summary.notes
    assert "missing_critical=route" in snap.quality_summary.notes
    assert quality_status_for_block() == "PARTIAL"


def quality_status_for_block() -> str:
    summary = summarize_quality(
        {},
        required=frozenset({"route"}),
        dimensions=QualityDimensions(None, None, None, None, None),
        policy=QualityPolicy("review-1", 0.8, 0.85),
        identity_valid=True,
        geometry_valid=True,
    )
    return quality_status(summary)


def test_snapshot_rejects_two_routes_and_bad_timezone() -> None:
    snap = snapshot()
    with pytest.raises(ValueError):
        IntegratedTravelContext.model_validate(
            snap.model_dump() | {"route_candidates": snap.route_candidates * 2}
        )
    with pytest.raises(ValueError):
        TravelWindow(starts_at=DEPARTURE, ends_at=DEPARTURE, timezone="Mars/Olympus")


def test_conflicts_are_carried_to_summary() -> None:
    conflict = QualityConflict(
        field_path="severity",
        source_ids=["usgs:captured-event", "official:conflicting-event"],
        resolution="UNRESOLVED",
    )
    snap = snapshot()
    rebuilt = IntegratedTravelContext.model_validate(
        snap.model_dump() | {"conflict_summary": [conflict]}
    )
    assert rebuilt.conflict_summary[0].resolution == "UNRESOLVED"


@pytest.mark.asyncio
async def test_corridor_buffer_is_polygonal_and_splits_at_dateline(isolated_database: str) -> None:
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine) as session:
            bangkok = sample_route(GeoLineString(type="LineString", coordinates=LINE),
                                   departure_at=DEPARTURE, duration_seconds=600,
                                   max_spacing_m=500)  # fmt: skip
            area = await corridor_buffer_geojson(session, bangkok, radius_m=1000)
            assert area["type"] == "MultiPolygon" and len(area["coordinates"]) == 1
            fiji = sample_route(
                GeoLineString(type="LineString",
                              coordinates=[(179.57103, -16.55536), (-179.82872, -16.414762)]),
                departure_at=DEPARTURE, duration_seconds=3600, max_spacing_m=5000,
            )  # fmt: skip
            split = await corridor_buffer_geojson(session, fiji, radius_m=2000)
            assert split["type"] == "MultiPolygon" and len(split["coordinates"]) == 2
            longitudes = [p[0] for poly in split["coordinates"] for p in poly[0]]
            assert max(longitudes) - min(longitudes) > 300  # two sides, not one wrap
            assert all(-180 <= lon <= 180 for lon in longitudes)
            with pytest.raises(ValueError):
                await corridor_buffer_geojson(session, fiji, radius_m=0)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_save_is_idempotent_immutable_and_checks_supersedes(isolated_database: str) -> None:
    engine = build_engine(isolated_database)
    request_id = uuid4()
    key = "sha256:" + "c" * 64
    try:
        factory = build_session_factory(engine)
        first = snapshot(request_id=request_id)
        async with unit_of_work(factory) as session:
            stored = await SnapshotRepository(session).save(first, input_content_hash=key)
            assert stored.id == first.snapshot_id
            assert stored.evidence_json["content_hash"] == first.content_hash
        replay = snapshot(request_id=request_id, created_at=datetime(2026, 9, 20, 19, tzinfo=UTC))
        async with unit_of_work(factory) as session:
            again = await SnapshotRepository(session).save(replay, input_content_hash=key)
            assert again.id == first.snapshot_id
        with pytest.raises(SnapshotConflictError):
            async with unit_of_work(factory) as session:
                await SnapshotRepository(session).save(
                    snapshot(request_id=request_id, official=False), input_content_hash=key
                )
        with pytest.raises(SnapshotNotFoundError):
            async with unit_of_work(factory) as session:
                await SnapshotRepository(session).save(
                    snapshot(supersedes=uuid4()), input_content_hash="sha256:" + "d" * 64
                )
        refresh = snapshot(supersedes=first.snapshot_id)
        async with unit_of_work(factory) as session:
            newer = await SnapshotRepository(session).save(
                refresh, input_content_hash="sha256:" + "e" * 64
            )
            assert newer.supersedes_id == first.snapshot_id
    finally:
        await engine.dispose()
