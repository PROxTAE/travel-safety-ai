"""PostGIS geography corridor queries with explicit temporal bounds."""

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.corridor import RouteSample, split_dateline

# Shared with the EXPLAIN checks in tests so the measured plan is the served plan.
# The corridor is parsed once in a materialized CTE: under a generic prepared plan an
# inline ST_GeomFromGeoJSON(:route) was re-parsed for every row, 30x slower at 50k rows.
HAZARD_QUERY = """
        WITH corridor AS MATERIALIZED (
            SELECT ST_GeomFromGeoJSON(:route)::geography AS shape
        )
        SELECT record.id
        FROM integration.canonical_records AS record, corridor
        WHERE record.record_type = 'disaster'
          AND record.geometry IS NOT NULL
          AND record.valid_at <= :end_at
          AND (
            record.payload_json ->> 'ends_at' IS NULL
            OR (record.payload_json ->> 'ends_at')::timestamptz >= :start_at
          )
          AND ST_DWithin(record.geometry::geography, corridor.shape, :radius_m)
        ORDER BY record.id
    """


@dataclass(frozen=True)
class GeometryHealth:
    valid: bool
    reason: str


async def geometry_health(session: AsyncSession, geometry: dict) -> GeometryHealth:
    """Ask PostGIS whether a sourced geometry is safe for spatial predicates."""
    result = await session.execute(
        text("""
            SELECT ST_IsValid(shape), ST_IsValidReason(shape)
            FROM (SELECT ST_GeomFromGeoJSON(:geometry) AS shape) AS candidate
        """),
        {"geometry": json.dumps(geometry, separators=(",", ":"))},
    )
    valid, reason = result.one()
    return GeometryHealth(bool(valid), str(reason))


def corridor_geojson(samples: list[RouteSample]) -> str:
    return json.dumps(
        {"type": "MultiLineString", "coordinates": split_dateline(samples)}, separators=(",", ":")
    )


async def point_within_corridor(
    session: AsyncSession,
    samples: list[RouteSample],
    *,
    longitude: float,
    latitude: float,
    radius_m: float,
) -> bool:
    if radius_m < 0:
        raise ValueError("corridor radius must be nonnegative")
    value = await session.scalar(
        text("""
        SELECT ST_DWithin(
            ST_GeomFromGeoJSON(:route)::geography,
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
            :radius_m
        )
    """),
        {
            "route": corridor_geojson(samples),
            "longitude": longitude,
            "latitude": latitude,
            "radius_m": radius_m,
        },
    )
    return bool(value)


async def hazard_ids_in_corridor(
    session: AsyncSession,
    samples: list[RouteSample],
    *,
    radius_m: float,
    start_at: datetime,
    end_at: datetime,
) -> list[UUID]:
    if radius_m < 0 or start_at.utcoffset() is None or end_at.utcoffset() is None:
        raise ValueError("radius and timezone-aware travel window required")
    if end_at < start_at:
        raise ValueError("travel window ends before it starts")
    result = await session.execute(
        text(HAZARD_QUERY),
        {
            "route": corridor_geojson(samples),
            "radius_m": radius_m,
            "start_at": start_at,
            "end_at": end_at,
        },
    )
    return list(result.scalars())


async def corridor_buffer_geojson(
    session: AsyncSession, samples: list[RouteSample], *, radius_m: float
) -> dict:
    """Buffer each dateline part on geography so no polygon wraps the globe."""
    if radius_m <= 0:
        raise ValueError("corridor radius must be positive")
    value = await session.scalar(
        text("""
        SELECT ST_AsGeoJSON(
            ST_CollectionExtract(
                ST_Collect(ST_Buffer((part).geom::geography, :radius_m)::geometry), 3
            ),
            7
        )
        FROM ST_Dump(ST_GeomFromGeoJSON(:route)) AS part
    """),
        {"route": corridor_geojson(samples), "radius_m": radius_m},
    )
    if value is None:
        raise ValueError("corridor buffer could not be built")
    return json.loads(value)
