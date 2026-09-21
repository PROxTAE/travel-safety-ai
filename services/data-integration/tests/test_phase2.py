"""Phase 2 checks using the public USGS event captured by module 04.

Provenance: external-data/tests/fixtures/real-sanitized/usgs/significant_month.json,
USGS public domain, HTTP 200, captured 2026-09-19T07:45:38Z, event us7000ti1p.
Only timestamp/coordinates/magnitude/title are copied from that response.
"""

import copy
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.canonical import RouteCandidate, TransportStatus
from app.pipeline.normalize import (
    canonicalize_value,
    convert_unit,
    field_paths,
    normalize_country_code,
    normalize_place,
    normalize_record,
    normalize_severity,
    route_for_contract,
    transform_checksum,
    utc_time,
)
from app.repositories.canonical_repo import CanonicalRepository
from app.repositories.models import CanonicalRecord, Quarantine
from app.repositories.snapshot_repo import canonical_hash


def usgs_record() -> dict:
    path = Path(__file__).parent / "fixtures" / "m04-usgs-event.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture["_provenance"]["http_status"] == 200
    return fixture["records"][0]


def test_pure_transforms_preserve_null_and_zero() -> None:
    assert convert_unit(None, "mph", "kmh") is None
    assert convert_unit(0, "mph", "kmh") == 0
    assert convert_unit(32, "fahrenheit", "celsius") == 0
    assert normalize_place("  New   York  ") == "new york"
    assert normalize_country_code(" th ") == "TH"
    assert normalize_country_code(None) is None
    with pytest.raises(ValueError):
        normalize_country_code("Thailand")
    assert normalize_severity("red") == "UNKNOWN"
    assert normalize_severity("SEVERE") == "SEVERE"
    nested = {"segments": [{"departure_time": datetime(2026, 1, 1, 7, tzinfo=timezone_bkk)}]}
    assert canonicalize_value(nested) == {"segments": [{"departure_time": "2026-01-01T00:00:00Z"}]}
    assert field_paths(nested) == ["segments.0.departure_time"]
    assert utc_time(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00Z"
    assert transform_checksum().startswith("sha256:")
    with pytest.raises(ValueError):
        utc_time(datetime(2026, 1, 1))


timezone_bkk = timezone(timedelta(hours=7))


def test_raw_route_to_plural_contract_provenance() -> None:
    """ORS HTTP 200 capture, 2026-09-20T07:50:14Z; see module 04 fixture manifest."""
    route = RouteCandidate.model_validate(
        {
            "route_id": "ors:bangkok-ayutthaya",
            "label": "ORIGINAL",
            "mode": "CAR",
            "geometry": {
                "type": "LineString",
                "coordinates": [[100.538733, 13.764725], [100.538688, 13.76462]],
            },
            "distance_m": 73688.3,
            "duration_seconds": 3183.8,
            "transfers": 0,
            "exposure": None,
            "risk_level": "UNKNOWN",
            "quality": {"status": "FRESH", "flags": ["INCOMPLETE"]},
            "sources": [
                {
                    "source_id": "openrouteservice:captured-route",
                    "provider": "openrouteservice",
                    "authority": "LICENSED_PROVIDER",
                    "fetched_at": "2026-09-20T07:50:14Z",
                    "schema_version": "1.0.0",
                }
            ],
        }
    )
    output = route_for_contract(route)
    assert "source" not in output
    assert len(output["sources"]) == 1
    assert output["sources"][0]["provider"] == "openrouteservice"
    assert output["exposure"] is None and output["risk_level"] == "UNKNOWN"
    payload, lineage = normalize_record(route)
    assert payload["sources"] == output["sources"]
    assert lineage["distance_m"]["source_ids"] == ["openrouteservice:captured-route"]


async def test_current_m04_route_sample_ingests_with_all_sources(isolated_database: str) -> None:
    """M04 handoff route from ORS real-sanitized capture, merged in main commit 3353f15."""
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "m04-route-candidates.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["_provenance"]["http_status"] == 200
    sample = fixture["records"][0]
    assert sample["sources"] and "source" not in sample
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            stored = await CanonicalRepository(session).ingest("route", sample)
            await session.commit()
            assert stored is not None
            assert (
                stored.payload_json["sources"][0]["source_id"] == sample["sources"][0]["source_id"]
            )
            assert stored.lineage_json["distance_m"]["source_ids"] == [
                sample["sources"][0]["source_id"]
            ]
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "kind,filename",
    [
        ("weather", "m04-weather-forecast-points.json"),
        ("transport", "m04-transport-statuses.json"),
        ("place", "m04-emergency-places.json"),
    ],
)
async def test_other_current_m04_samples_ingest(
    isolated_database: str, kind: str, filename: str
) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / filename).read_text(encoding="utf-8")
    )
    assert fixture["_provenance"]["http_status"] == 200
    sample = fixture["records"][0]
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            stored = await CanonicalRepository(session).ingest(kind, sample)
            await session.commit()
            assert stored is not None
            assert stored.record_type == kind
            assert stored.payload_json["source"]["source_id"] == sample["source"]["source_id"]
    finally:
        await engine.dispose()


def test_transit_stop_keys_preserve_captured_names() -> None:
    """MTA static GTFS HTTP 200 capture, 2026-09-20T13:33:21Z; module 04 manifest."""
    record = TransportStatus.model_validate(
        {
            "id": "mta:A02N-A03N",
            "mode": "TRAIN",
            "status": "UNKNOWN",
            "origin_stop": {"stop_id": "A02N", "name": "Inwood-207 St"},
            "destination_stop": {"stop_id": "A03N", "name": "Dyckman St"},
            "quality": {"status": "UNAVAILABLE", "flags": ["MISSING"]},
            "source": {
                "source_id": "mta:static:A02N-A03N",
                "provider": "mta",
                "authority": "OFFICIAL",
                "fetched_at": "2026-09-20T13:33:21Z",
                "schema_version": "1.0.0",
            },
        }
    )
    payload, lineage = normalize_record(record)
    assert payload["origin_stop"]["name"] == "Inwood-207 St"
    assert payload["canonical_origin_stop_key"] == "inwood-207 st"
    assert lineage["canonical_destination_stop_key"]["source_path"] == "destination_stop.name"


@pytest.mark.parametrize(
    "field,value",
    [
        ("magnitude", float("nan")),
        ("effective_at", "2026-09-17T14:19:52"),
        ("geometry", {"type": "Point", "coordinates": [52.8594, -171.3756]}),
    ],
)
async def test_invalid_input_is_quarantined(
    isolated_database: str, field: str, value: object
) -> None:
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            payload = usgs_record()
            payload[field] = value
            assert await CanonicalRepository(session).ingest("disaster", payload) is None
            await session.commit()
            assert (await session.scalar(select(func.count()).select_from(Quarantine))) >= 1
    finally:
        await engine.dispose()


async def test_canonical_upsert_keeps_lineage_and_geometry(isolated_database: str) -> None:
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            repository = CanonicalRepository(session)
            first = await repository.ingest("disaster", usgs_record())
            second = await repository.ingest("disaster", copy.deepcopy(usgs_record()))
            await session.commit()
            assert first is not None and second is not None
            assert first.id == second.id
            assert first.payload_json["canonical_geometry"]["coordinates"] == [-171.3756, 52.8594]
            assert first.lineage_json["magnitude"]["source_id"] == "usgs_earthquake:us7000ti1p"
            assert first.lineage_json["canonical_geometry.coordinates.0"]["source_path"] == (
                "geometry.coordinates.0"
            )
            assert first.lineage_json["canonical_severity"]["source_path"] == "severity"
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(CanonicalRecord)
                    .where(
                        CanonicalRecord.source_id == "usgs_earthquake:us7000ti1p",
                        CanonicalRecord.content_hash == first.content_hash,
                    )
                )
            ) == 1
    finally:
        await engine.dispose()


async def test_copied_observation_time_is_quarantined(isolated_database: str) -> None:
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine) as session:
            before = await session.scalar(select(func.count()).select_from(Quarantine))
            payload = usgs_record()
            payload["source"]["observed_at"] = payload["source"]["fetched_at"]
            assert await CanonicalRepository(session).ingest("disaster", payload) is None
            await session.commit()
            assert await session.scalar(select(func.count()).select_from(Quarantine)) == before + 1
    finally:
        await engine.dispose()


async def test_generated_required_field_is_quarantined(isolated_database: str) -> None:
    sample = usgs_record()
    del sample["quality"]["score_version"]
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine) as session:
            assert await CanonicalRepository(session).ingest("disaster", sample) is None
            await session.flush()
            error = (
                await session.execute(
                    select(Quarantine).where(Quarantine.source_hash == canonical_hash(sample))
                )
            ).scalar_one()
            assert error.field_path == "quality.score_version"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("geometry_type", ["Polygon", "MultiPolygon"])
async def test_sourced_area_geometry_is_persisted(
    isolated_database: str, geometry_type: str
) -> None:
    """Test-only square around the captured USGS event coordinate."""
    ring = [
        [-171.38, 52.85],
        [-171.37, 52.85],
        [-171.37, 52.86],
        [-171.38, 52.86],
        [-171.38, 52.85],
    ]
    sample = usgs_record()
    sample["geometry"] = {
        "type": geometry_type,
        "coordinates": [ring] if geometry_type == "Polygon" else [[ring]],
    }
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine) as session:
            stored = await CanonicalRepository(session).ingest("disaster", sample)
            assert stored is not None
            assert stored.payload_json["canonical_geometry"]["type"] == geometry_type
    finally:
        await engine.dispose()


async def test_self_intersecting_polygon_is_quarantined(isolated_database: str) -> None:
    """Test-only bowtie mutation around the captured USGS event coordinate."""
    sample = usgs_record()
    sample["geometry"] = {
        "type": "Polygon",
        "coordinates": [
            [
                [-171.38, 52.85],
                [-171.37, 52.86],
                [-171.37, 52.85],
                [-171.38, 52.86],
                [-171.38, 52.85],
            ]
        ],
    }
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine) as session:
            assert await CanonicalRepository(session).ingest("disaster", sample) is None
            error = (
                await session.execute(
                    select(Quarantine).where(Quarantine.source_hash == canonical_hash(sample))
                )
            ).scalar_one()
            assert error.error_code == "INVALID_INPUT"
    finally:
        await engine.dispose()
