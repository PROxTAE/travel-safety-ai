from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from app.contracts import (
    DataQuality,
    DataStatus,
    IntegratedTravelContext,
    ModelReference,
    RiskAssessment,
    RiskLevel,
    RouteCandidate,
    SafetyOverride,
    Severity,
)

FALLBACK_POLICY_VERSION = "fallback-safety-1.0.0"


def assess_with_conservative_fallback(
    snapshot: IntegratedTravelContext, route_ids: list[UUID]
) -> list[RiskAssessment]:
    """Apply only explicit hard facts; never infer LOW risk from missing model evidence."""

    routes = {route.route_id: route for route in snapshot.route_candidates}
    return [_assess_route(snapshot, routes[route_id], datetime.now(UTC)) for route_id in route_ids]


def _assess_route(
    snapshot: IntegratedTravelContext,
    route: RouteCandidate,
    created_at: datetime,
) -> RiskAssessment:
    route_id = cast(UUID, route.route_id)
    reason_codes: list[str] = ["MODEL_UNAVAILABLE", "FALLBACK_RULE_APPLIED"]
    overrides: list[SafetyOverride] = []
    source_ids: set[UUID] = set()

    if route.exposure is not None and (
        route.exposure.closed or route.exposure.hard_constraint_codes
    ):
        reason_codes.insert(0, "OFFICIAL_CLOSURE")
        for source in route.sources:
            source_ids.add(cast(UUID, source.source_id))
        overrides.append(
            SafetyOverride(
                code="OFFICIAL_CLOSURE",
                applied_risk_level=RiskLevel.HIGH,
                source_ids=sorted(source_ids, key=str),
                policy_version=FALLBACK_POLICY_VERSION,
            )
        )

    for alert in snapshot.official_alerts:
        applies = not alert.affected_route_ids or route_id in alert.affected_route_ids
        if not applies or not alert.is_active_during(
            snapshot.travel_window.starts_at, snapshot.travel_window.ends_at
        ):
            continue
        if alert.closure and not any(item.code == "OFFICIAL_CLOSURE" for item in overrides):
            reason_codes.insert(0, "OFFICIAL_CLOSURE")
            overrides.append(
                SafetyOverride(
                    code="OFFICIAL_CLOSURE",
                    applied_risk_level=RiskLevel.HIGH,
                    source_ids=[alert.source.source_id],
                    policy_version=FALLBACK_POLICY_VERSION,
                )
            )
        if alert.evacuation:
            reason_codes.insert(0, "OFFICIAL_EVACUATION")
            overrides.append(
                SafetyOverride(
                    code="OFFICIAL_EVACUATION",
                    applied_risk_level=RiskLevel.HIGH,
                    source_ids=[alert.source.source_id],
                    policy_version=FALLBACK_POLICY_VERSION,
                )
            )
        if alert.severity == Severity.EXTREME:
            reason_codes.insert(0, "EXTREME_WARNING_CORRIDOR")
            overrides.append(
                SafetyOverride(
                    code="EXTREME_WARNING_CORRIDOR",
                    applied_risk_level=RiskLevel.HIGH,
                    source_ids=[alert.source.source_id],
                    policy_version=FALLBACK_POLICY_VERSION,
                )
            )

    risk_level = RiskLevel.HIGH if overrides else RiskLevel.UNKNOWN
    if not overrides:
        overrides.append(
            SafetyOverride(
                code="MISSING_CRITICAL_EVIDENCE",
                applied_risk_level=RiskLevel.UNKNOWN,
                source_ids=[],
                policy_version=FALLBACK_POLICY_VERSION,
            )
        )
        reason_codes.insert(0, "LIMITED_CRITICAL_COVERAGE")

    return RiskAssessment(
        assessment_id=uuid4(),
        snapshot_id=snapshot.snapshot_id,
        route_id=route_id,
        score=None,
        probability_high=None,
        risk_level=risk_level,
        uncertainty=1.0,
        reason_codes=list(dict.fromkeys(reason_codes)),
        safety_overrides=overrides,
        model=ModelReference(
            name="deterministic-safety-fallback",
            version=FALLBACK_POLICY_VERSION,
            feature_schema_version="1.0.0",
            artifact_checksum=None,
        ),
        quality=DataQuality(
            status=DataStatus.PARTIAL,
            score=None,
            score_version=None,
            flags=["MISSING", "INCOMPLETE"],
            coverage=snapshot.quality_summary.coverage,
            completeness=snapshot.quality_summary.completeness,
            freshness_seconds=snapshot.quality_summary.freshness_seconds,
            conflicts=snapshot.quality_summary.conflicts,
            notes=["Local model unavailable; deterministic safety fallback applied."],
        ),
        created_at=created_at,
    )
