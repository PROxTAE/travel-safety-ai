"""Pure canonical transforms; inputs retain their original provider fields."""

import hashlib
import inspect
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, cast

from app.domain.canonical import (
    GeoLineString,
    GeoMultiPolygon,
    GeoPoint,
    GeoPolygon,
    RecordModel,
    RouteCandidate,
    SourceProvenance,
    TransportStatus,
)
from app.repositories.snapshot_repo import canonical_hash

TRANSFORM_VERSION = "1.0.0"
SEVERITIES = frozenset({"INFO", "MINOR", "MODERATE", "SEVERE", "EXTREME", "UNKNOWN"})


def convert_unit(value: float | None, source: str, target: str) -> float | None:
    if value is None:
        return None
    factors = {
        ("fahrenheit", "celsius"): (Decimal(5) / Decimal(9), Decimal(-32)),
        ("mph", "kmh"): (Decimal("1.609344"), Decimal(0)),
        ("mps", "kmh"): (Decimal("3.6"), Decimal(0)),
        ("inches", "mm"): (Decimal("25.4"), Decimal(0)),
        ("miles", "m"): (Decimal("1609.344"), Decimal(0)),
        ("km", "m"): (Decimal(1000), Decimal(0)),
        ("minutes", "seconds"): (Decimal(60), Decimal(0)),
        ("hours", "seconds"): (Decimal(3600), Decimal(0)),
    }
    if source == target:
        return value
    factor, offset = factors[(source, target)]
    result = (Decimal(str(value)) + offset) * factor
    if not result.is_finite():
        raise ValueError("non-finite unit result")
    return float(result.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))


def utc_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonicalize_value(value: object) -> object:
    """Convert all nested timestamps to UTC without changing nulls or zeroes."""
    if isinstance(value, datetime):
        return utc_time(value)
    if isinstance(value, dict):
        return {key: canonicalize_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [canonicalize_value(item) for item in value]
    return value


def field_paths(value: object, prefix: str = "") -> list[str]:
    """Enumerate leaf paths so nested measurements have their own lineage."""
    if isinstance(value, dict):
        return [
            path
            for key, item in value.items()
            for path in field_paths(item, f"{prefix}.{key}" if prefix else key)
        ]
    if isinstance(value, list):
        return [
            path
            for index, item in enumerate(value)
            for path in field_paths(item, f"{prefix}.{index}")
        ]
    return [prefix]


def normalize_place(value: str | None) -> str | None:
    return " ".join(value.split()).casefold() if value is not None else None


def normalize_country_code(value: str | None) -> str | None:
    if value is None:
        return None
    code = value.strip().upper()
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        raise ValueError("country code must be two ASCII letters")
    return code


def normalize_severity(value: str | None) -> str:
    """Preserve an approved canonical value; unknown provider scales stay UNKNOWN."""
    return value if value in SEVERITIES else "UNKNOWN"


def normalize_line(line: GeoLineString) -> dict[str, Any]:
    points: list[tuple[float, float]] = []
    for point in line.coordinates:
        if not points or points[-1] != point:
            points.append(point)
    if len(points) < 2:
        raise ValueError("line has fewer than two distinct vertices")
    return {"type": "LineString", "coordinates": [list(point) for point in points]}


def geometry_of(record: RecordModel) -> dict[str, Any] | None:
    geometry = getattr(record, "geometry", None) or getattr(record, "location", None)
    if isinstance(geometry, GeoLineString):
        return normalize_line(geometry)
    if isinstance(geometry, GeoPoint | GeoPolygon | GeoMultiPolygon):
        return geometry.model_dump(mode="json")
    return None


def route_for_contract(route: RouteCandidate) -> dict[str, Any]:
    """Preserve the producer's plural provenance in the shared route shape."""
    return cast(dict[str, Any], canonicalize_value(route.model_dump(mode="python")))


def record_sources(record: RecordModel) -> list[SourceProvenance]:
    return record.sources if isinstance(record, RouteCandidate) else [record.source]


def transform_checksum() -> str:
    source = inspect.getsource(convert_unit) + inspect.getsource(utc_time)
    source += inspect.getsource(canonicalize_value) + inspect.getsource(field_paths)
    source += inspect.getsource(normalize_place) + inspect.getsource(normalize_country_code)
    source += inspect.getsource(normalize_severity)
    source += inspect.getsource(normalize_line) + inspect.getsource(normalize_record)
    return "sha256:" + hashlib.sha256(source.encode()).hexdigest()


def normalize_record(record: RecordModel) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = cast(dict[str, Any], canonicalize_value(record.model_dump(mode="python")))
    sources = record_sources(record)
    geometry = geometry_of(record)
    if geometry is not None:
        payload["canonical_geometry"] = geometry
    if hasattr(record, "severity"):
        payload["canonical_severity"] = normalize_severity(record.severity)
    if hasattr(record, "name"):
        payload["canonical_place_key"] = normalize_place(record.name)
    if isinstance(record, TransportStatus):
        payload["canonical_origin_stop_key"] = normalize_place(record.origin_stop.name)
        payload["canonical_destination_stop_key"] = normalize_place(record.destination_stop.name)
    checksum = transform_checksum()
    derived_paths = {
        "canonical_geometry": "geometry" if hasattr(record, "geometry") else "location",
        "canonical_severity": "severity",
        "canonical_place_key": "name",
        "canonical_origin_stop_key": "origin_stop.name",
        "canonical_destination_stop_key": "destination_stop.name",
    }

    def source_path(field: str) -> str:
        for derived, origin in derived_paths.items():
            if field == derived or field.startswith(f"{derived}."):
                return origin + field[len(derived) :]
        return field

    lineage = {
        field: {
            "source_id": sources[0].source_id,
            "source_ids": [source.source_id for source in sources],
            "source_path": source_path(field),
            "transform_version": TRANSFORM_VERSION,
            "transform_checksum": checksum,
        }
        for field in field_paths(payload)
    }
    payload["canonical_content_hash"] = canonical_hash(payload)
    return payload, lineage
