"""Run the whole pipeline for one route: features, quality, corridor and snapshot."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.canonical import (
    DataQuality,
    DisasterEvent,
    QualityConflict,
    RouteCandidate,
    TransportStatus,
    WeatherForecastPoint,
)
from app.domain.snapshot import IntegratedTravelContext, SnapshotCreateRequest, TravelWindow
from app.pipeline.corridor import RouteSample, sample_route
from app.pipeline.dedup import candidate_links, exact_clusters, resolve_field
from app.pipeline.features import (
    TRANSIT_MODES,
    FeatureInputs,
    FeaturePolicy,
    FeatureVector,
    before_cutoff,
    build_features,
)
from app.pipeline.quality import (
    QualityPolicy,
    measure_dimensions,
    summarize_quality,
)
from app.pipeline.snapshot import assemble_snapshot
from app.pipeline.spatial import corridor_buffer_geojson, geometry_health
from app.settings import Settings

QUALITY_POLICY_VERSION = "quality.gate/0.1.0"


@dataclass(frozen=True)
class RouteEvidence:
    """Records for one route; None means the source was unavailable."""

    route: RouteCandidate
    weather: list[WeatherForecastPoint] | None
    disasters: list[DisasterEvent] | None
    transport: list[TransportStatus] | None
    source_quality: dict[str, DataQuality]


def evidence_from_request(body: SnapshotCreateRequest) -> RouteEvidence:
    return RouteEvidence(
        body.route,
        body.evidence.weather,
        body.evidence.disaster_events,
        body.evidence.transport,
        body.source_quality,
    )


def _disaster_conflicts(
    disasters: list[DisasterEvent], settings: Settings
) -> tuple[int, list[QualityConflict]]:
    """Count multi-source events and the ones whose sources disagree on severity."""
    records = [event.model_dump(mode="json") for event in disasters]
    links = candidate_links(
        records,
        max_distance_m=settings.duplicate_distance_m,
        max_time_seconds=settings.duplicate_time_seconds,
    )
    comparable = 0
    conflicts: list[QualityConflict] = []
    for cluster in exact_clusters(records, links):
        if len(cluster.members) < 2:
            continue
        comparable += 1
        resolution = resolve_field([records[i] for i in cluster.members], "severity")
        if resolution.status == "CONFLICTING":
            conflicts.append(
                QualityConflict(
                    field_path="disaster_events.severity",
                    source_ids=sorted(cluster.source_ids),
                    resolution="UNRESOLVED",
                )
            )
    return comparable, conflicts


def compute_route_features(
    evidence: RouteEvidence,
    *,
    travel_window: TravelWindow,
    recommendation_at: datetime,
    settings: Settings,
) -> tuple[RouteEvidence, list[RouteSample], FeatureVector]:
    """The one feature path shared by the online API and the offline batch CLI."""
    route = evidence.route
    # Records learned after the recommendation stay out of features and the snapshot alike.
    known = RouteEvidence(
        route,
        before_cutoff(evidence.weather, recommendation_at),
        before_cutoff(evidence.disasters, recommendation_at),
        before_cutoff(evidence.transport, recommendation_at),
        evidence.source_quality,
    )
    samples = sample_route(
        route.geometry,
        departure_at=travel_window.starts_at,
        duration_seconds=route.duration_seconds,
        max_spacing_m=settings.route_sample_spacing_m,
    )
    features = build_features(
        FeatureInputs(
            route,
            samples,
            recommendation_at,
            known.weather,
            known.disasters,
            known.transport,
            known.source_quality,
        ),
        FeaturePolicy(
            weather_radius_m=settings.corridor_radius_m,
            weather_time_tolerance_seconds=settings.weather_time_tolerance_seconds,
            transport_time_tolerance_seconds=settings.transport_time_tolerance_seconds,
        ),
    )
    return known, samples, features


async def _geometry_valid(session: AsyncSession, evidence: RouteEvidence) -> bool:
    shapes = [evidence.route.geometry.model_dump(mode="json")]
    shapes += [
        event.geometry.model_dump(mode="json")
        for event in evidence.disasters or []
        if event.geometry.type != "Point"
    ]
    for shape in shapes:
        if not (await geometry_health(session, shape)).valid:
            return False
    return True


async def build_route_snapshot(
    session: AsyncSession,
    *,
    snapshot_id: UUID,
    request_id: UUID,
    trip_id: UUID,
    supersedes_snapshot_id: UUID | None,
    travel_window: TravelWindow,
    recommendation_at: datetime,
    evidence: RouteEvidence,
    settings: Settings,
    created_at: datetime,
) -> IntegratedTravelContext:
    route = evidence.route
    evidence, samples, features = compute_route_features(
        evidence,
        travel_window=travel_window,
        recommendation_at=recommendation_at,
        settings=settings,
    )
    required = {"route", "weather", "disaster"}
    if route.mode in TRANSIT_MODES:
        required.add("transport")
    comparable, conflicts = _disaster_conflicts(evidence.disasters or [], settings)
    authorities = [s.authority for s in route.sources]
    authorities += [r.source.authority for r in evidence.weather or []]
    authorities += [r.source.authority for r in evidence.disasters or []]
    coverage = features.values["critical_evidence_coverage"]
    dimensions = measure_dimensions(
        evidence.source_quality,
        required=frozenset(required),
        coverage=float(coverage) if isinstance(coverage, int | float) else None,
        comparable_facts=comparable,
        unresolved_conflicts=len(conflicts),
        authorities=authorities,
    )
    quality = summarize_quality(
        evidence.source_quality,
        required=frozenset(required),
        dimensions=dimensions,
        policy=QualityPolicy(
            QUALITY_POLICY_VERSION,
            settings.quality_minimum_coverage,
            settings.quality_minimum_score,
        ),
        identity_valid=True,
        geometry_valid=await _geometry_valid(session, evidence),
        unresolved_conflicts=len(conflicts),
    )
    corridor = await corridor_buffer_geojson(session, samples, radius_m=settings.corridor_radius_m)
    return assemble_snapshot(
        snapshot_id=snapshot_id,
        request_id=request_id,
        trip_id=trip_id,
        supersedes_snapshot_id=supersedes_snapshot_id,
        travel_window=travel_window,
        route=route,
        corridor=corridor,
        corridor_radius_m=settings.corridor_radius_m,
        weather=evidence.weather or [],
        transport=evidence.transport or [],
        disasters=evidence.disasters or [],
        features=features,
        quality=quality,
        conflicts=conflicts,
        created_at=created_at,
    )
