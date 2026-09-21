"""Assemble one immutable IntegratedTravelContext for one route candidate."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.domain.canonical import (
    DataQuality,
    DisasterEvent,
    QualityConflict,
    RouteCandidate,
    TransportStatus,
    WeatherForecastPoint,
)
from app.domain.snapshot import IntegratedTravelContext, TravelWindow
from app.pipeline.features import FeatureVector
from app.pipeline.quality import QualitySummary
from app.repositories.snapshot_repo import canonical_hash

SNAPSHOT_SCHEMA_VERSION = "1.0.0"
# Identity and timing differ on every replay, so they stay out of the content hash.
UNHASHED = {"snapshot_id", "created_at", "content_hash"}


def quality_status(
    summary: QualitySummary,
) -> Literal["FRESH", "STALE", "CONFLICTING", "PARTIAL"]:
    """Map the gate onto DataQuality.status without reporting FRESH for weak evidence."""
    if "CONFLICTING" in summary.flags:
        return "CONFLICTING"
    if summary.missing_critical:
        return "PARTIAL"
    if "STALE" in summary.flags:
        return "STALE"
    return "FRESH" if summary.gate == "PASS" else "PARTIAL"


def summary_quality(
    summary: QualitySummary, conflicts: list[QualityConflict], *, corridor_radius_m: float
) -> DataQuality:
    return DataQuality.model_validate(
        {
            "status": quality_status(summary),
            "score": summary.score,
            "score_version": summary.score_version if summary.score is not None else None,
            "flags": list(summary.flags),
            "coverage": summary.coverage,
            "conflicts": conflicts,
            # The contract has no gate field yet; consumers read these notes until it does.
            "notes": [
                f"gate={summary.gate}",
                f"quality_policy={summary.policy_version}",
                f"corridor_radius_m={corridor_radius_m:g}",
                *(f"missing_critical={name}" for name in summary.missing_critical),
            ],
        }
    )


def assemble_snapshot(
    *,
    snapshot_id: UUID,
    request_id: UUID,
    trip_id: UUID,
    supersedes_snapshot_id: UUID | None,
    travel_window: TravelWindow,
    route: RouteCandidate,
    corridor: dict,
    corridor_radius_m: float,
    weather: list[WeatherForecastPoint],
    transport: list[TransportStatus],
    disasters: list[DisasterEvent],
    features: FeatureVector,
    quality: QualitySummary,
    conflicts: list[QualityConflict],
    created_at: datetime,
) -> IntegratedTravelContext:
    """Build the snapshot and hash everything except its identity and creation time."""
    sources = [
        *(s.source_id for s in route.sources),
        *(r.source.source_id for r in weather),
        *(r.source.source_id for r in transport),
        *(r.source.source_id for r in disasters),
    ]
    body = {
        "request_id": request_id,
        "trip_id": trip_id,
        "supersedes_snapshot_id": supersedes_snapshot_id,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "feature_schema_version": features.schema_version,
        "travel_window": travel_window,
        "route_candidates": [route],
        "route_corridor_geojson": corridor,
        "weather": weather,
        "transport": transport,
        "disaster_events": disasters,
        # Since module 04 #35, official means a warning or order was issued.
        "official_alerts": [event for event in disasters if event.official],
        "features": features.values,
        "quality_summary": summary_quality(quality, conflicts, corridor_radius_m=corridor_radius_m),
        "conflict_summary": conflicts,
        "source_ids": sorted(set(sources)),
    }
    draft = IntegratedTravelContext.model_validate(
        body
        | {
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "content_hash": "sha256:" + "0" * 64,
        }
    )
    hashed = draft.model_dump(mode="json", exclude=UNHASHED)
    return draft.model_copy(update={"content_hash": canonical_hash(hashed)})
