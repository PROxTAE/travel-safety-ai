"""IntegratedTravelContext as defined in packages/contracts (common, schema 1.0.0).

One snapshot carries one route candidate, so its flat feature map belongs to that route.
"""

import re
from typing import Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.domain.canonical import (
    DataQuality,
    DisasterEvent,
    GeoMultiPolygon,
    GeoPolygon,
    QualityConflict,
    RouteCandidate,
    StrictRecord,
    TransportStatus,
    WeatherForecastPoint,
)

SEMVER = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$"
RECORD_ID = r"^[A-Za-z0-9][A-Za-z0-9._:,+@/=-]*$"
CONTENT_HASH = r"^(sha256:[0-9a-f]{64}|sha512:[0-9a-f]{128})$"
FeatureValue = float | int | bool | str | None


class TravelWindow(StrictRecord):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone must be an IANA zone") from error
        return value

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.ends_at < self.starts_at:
            raise ValueError("travel window ends before it starts")
        return self


class IntegratedTravelContext(StrictRecord):
    snapshot_id: UUID
    request_id: UUID
    trip_id: UUID
    supersedes_snapshot_id: UUID | None = None
    schema_version: str = Field(pattern=SEMVER)
    feature_schema_version: str = Field(pattern=SEMVER)
    travel_window: TravelWindow
    route_candidates: list[RouteCandidate] = Field(min_length=1, max_length=1)
    route_corridor_geojson: GeoPolygon | GeoMultiPolygon
    weather: list[WeatherForecastPoint]
    transport: list[TransportStatus]
    disaster_events: list[DisasterEvent]
    official_alerts: list[DisasterEvent]
    features: dict[str, FeatureValue]
    quality_summary: DataQuality
    conflict_summary: list[QualityConflict] = Field(default_factory=list)
    source_ids: list[str] = Field(min_length=1)
    created_at: AwareDatetime
    content_hash: str = Field(pattern=CONTENT_HASH)

    @field_validator("source_ids")
    @classmethod
    def record_ids(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(RECORD_ID, v) or len(v) > 256 for v in values):
            raise ValueError("source_ids must be RecordId values")
        return values


class Evidence(StrictRecord):
    weather: list[WeatherForecastPoint] | None
    disaster_events: list[DisasterEvent] | None
    transport: list[TransportStatus] | None


class SnapshotCreateRequest(StrictRecord):
    request_id: UUID
    trip_id: UUID
    supersedes_snapshot_id: UUID | None = None
    travel_window: TravelWindow
    recommendation_at: AwareDatetime
    route: RouteCandidate
    evidence: Evidence
    source_quality: dict[str, DataQuality]
