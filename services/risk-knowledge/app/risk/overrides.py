"""Versioned deterministic safety overrides (Phase 4)."""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts import RiskAssessment, RiskLevel

POLICY_VERSION = "safety-overrides-1.0.0"


@dataclass(frozen=True)
class OverrideRule:
    code: str
    minimum_level: RiskLevel


OVERRIDE_TABLE = (
    OverrideRule("OFFICIAL_CLOSURE", RiskLevel.HIGH),
    OverrideRule("OFFICIAL_EVACUATION", RiskLevel.HIGH),
    OverrideRule("EXTREME_WARNING_CORRIDOR", RiskLevel.HIGH),
    OverrideRule("MISSING_CRITICAL_EVIDENCE", RiskLevel.UNKNOWN),
    OverrideRule("OFFICIAL_SOURCE_CONFLICT", RiskLevel.UNKNOWN),
)

RISK_ORDER = {RiskLevel.UNKNOWN: -1, RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


def enforce_official_priority(assessment: RiskAssessment) -> RiskAssessment:
    levels = {item.applied_risk_level for item in assessment.safety_overrides}
    if RiskLevel.HIGH in levels and assessment.risk_level != RiskLevel.HIGH:
        return assessment.model_copy(update={"risk_level": RiskLevel.HIGH})
    if RiskLevel.UNKNOWN in levels and assessment.risk_level == RiskLevel.LOW:
        return assessment.model_copy(
            update={"risk_level": RiskLevel.UNKNOWN, "score": None, "probability_high": None}
        )
    return assessment


def validate_monotonic_override(before: RiskAssessment, after: RiskAssessment) -> None:
    """Reject an override that weakens a known risk assessment."""
    if before.risk_level is RiskLevel.UNKNOWN:
        return
    if RISK_ORDER[after.risk_level] < RISK_ORDER[before.risk_level]:
        raise ValueError("SAFETY_OVERRIDE_WEAKENED_RISK")
