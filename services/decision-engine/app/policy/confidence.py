from __future__ import annotations

from app.domain.models import DecisionRequest, RiskAssessment
from app.policy.loader import Policy


def evidence_confidence(payload: DecisionRequest, assessment: RiskAssessment) -> float:
    """Calculate confidence from evidence quality, coverage, completeness, and uncertainty."""
    quality = payload.quality_summary
    route_quality = assessment.quality
    components = [
        value
        for value in (
            quality.score,
            route_quality.score,
            quality.coverage,
            route_quality.coverage,
            quality.completeness,
            route_quality.completeness,
        )
        if value is not None
    ]
    base = sum(components) / len(components) if components else 0.0
    uncertainty = assessment.uncertainty or 0.0
    conflict_penalty = 0.15 if quality.status == "CONFLICTING" or quality.flags else 0.0
    return max(0.0, min(1.0, base * (1.0 - uncertainty) - conflict_penalty))


def near_threshold(assessment: RiskAssessment, policy: Policy) -> bool:
    if assessment.score is None:
        return False
    return (
        abs(assessment.score - policy.thresholds.high_risk_score)
        <= policy.thresholds.threshold_margin
    )
