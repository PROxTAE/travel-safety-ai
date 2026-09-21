"""PostGIS tests use coordinates captured from USGS and Open-Meteo providers.

USGS HTTP 200 2026-09-19T07:45:38Z; Open-Meteo Fiji HTTP 200
2026-09-20T14:43:47Z. Test-only route geometry is derived from captured points.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from geoalchemy2.elements import WKTElement
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.canonical import GeoLineString
from app.pipeline.corridor import sample_route
from app.pipeline.spatial import geometry_health, hazard_ids_in_corridor, point_within_corridor
from app.repositories.models import CanonicalRecord


async def test_postgis_geography_corridor_crosses_dateline(isolated_database: str) -> None:
    line = GeoLineString(
        type="LineString",
        coordinates=[
            (179.57103, -16.55536),
            (-179.82872, -16.414762),
        ],
    )
    samples = sample_route(
        line,
        departure_at=datetime(2026, 9, 20, 20, tzinfo=UTC),
        duration_seconds=3600,
        max_spacing_m=5000,
    )
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine) as session:
            assert await point_within_corridor(
                session, samples, longitude=179.57103, latitude=-16.55536, radius_m=1000
            )
            assert await point_within_corridor(
                session, samples, longitude=-179.82872, latitude=-16.414762, radius_m=1000
            )
            assert not await point_within_corridor(
                session, samples, longitude=0, latitude=0, radius_m=1000
            )
    finally:
        await engine.dispose()


async def test_hazard_join_requires_space_and_effective_time(isolated_database: str) -> None:
    event_time = datetime(2026, 9, 17, 14, 19, 52, tzinfo=UTC)
    line = GeoLineString(
        type="LineString",
        coordinates=[
            (-171.3756, 52.8594),
            (-171.3656, 52.8594),
        ],
    )
    samples = sample_route(line, departure_at=event_time, duration_seconds=600, max_spacing_m=1000)
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine) as session:
            matching_id, future_id = uuid4(), uuid4()
            for row_id, valid_at in [
                (matching_id, event_time),
                (future_id, event_time + timedelta(days=1)),
            ]:
                session.add(
                    CanonicalRecord(
                        id=row_id,
                        record_type="disaster",
                        source_id=f"usgs:{row_id}",
                        content_hash=f"sha256:{row_id.hex}",
                        schema_version="1.0.0",
                        transform_version="1.0.0",
                        payload_json={"ends_at": None},
                        lineage_json={},
                        geometry=WKTElement("POINT (-171.3756 52.8594)", srid=4326),
                        valid_at=valid_at,
                        fetched_at=event_time + timedelta(days=2),
                    )
                )
            await session.flush()
            result = await hazard_ids_in_corridor(
                session,
                samples,
                radius_m=1000,
                start_at=event_time,
                end_at=event_time + timedelta(minutes=10),
            )
            assert matching_id in result
            assert future_id not in result
    finally:
        await engine.dispose()


async def test_multipolygon_validity_and_self_intersection(isolated_database: str) -> None:
    """Squares are test geometries around the captured USGS earthquake point."""
    square = [
        [-171.38, 52.85],
        [-171.37, 52.85],
        [-171.37, 52.86],
        [-171.38, 52.86],
        [-171.38, 52.85],
    ]
    valid = {"type": "MultiPolygon", "coordinates": [[square]]}
    bowtie = {
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
            assert (await geometry_health(session, valid)).valid
            invalid = await geometry_health(session, bowtie)
            assert not invalid.valid
            assert "Self-intersection" in invalid.reason
    finally:
        await engine.dispose()


async def test_high_latitude_dateline_geography_is_metric(isolated_database: str) -> None:
    """Move the captured Fiji longitudes north to probe a polar edge case."""
    line = GeoLineString(type="LineString", coordinates=[(179.57103, 85.0), (-179.82872, 85.0)])
    samples = sample_route(
        line,
        departure_at=datetime(2026, 9, 20, 20, tzinfo=UTC),
        duration_seconds=3600,
        max_spacing_m=1000,
    )
    assert samples[-1].distance_m < 10_000
    engine = create_async_engine(isolated_database)
    try:
        async with AsyncSession(engine) as session:
            assert await point_within_corridor(
                session, samples, longitude=-179.82872, latitude=85.0, radius_m=100
            )
    finally:
        await engine.dispose()
