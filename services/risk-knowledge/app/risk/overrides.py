"""Versioned deterministic safety overrides (Phase 4)."""

from __future__ import annotations

from app.contracts import RiskAssessment, RiskLevel

POLICY_VERSION = "safety-overrides-1.0.0"


def enforce_official_priority(assessment: RiskAssessment) -> RiskAssessment:
    levels = {item.applied_risk_level for item in assessment.safety_overrides}
    if RiskLevel.HIGH in levels and assessment.risk_level != RiskLevel.HIGH:
        return assessment.model_copy(update={"risk_level": RiskLevel.HIGH})
    if RiskLevel.UNKNOWN in levels and assessment.risk_level == RiskLevel.LOW:
        return assessment.model_copy(
            update={"risk_level": RiskLevel.UNKNOWN, "score": None, "probability_high": None}
        )
    return assessment
