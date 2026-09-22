from __future__ import annotations

from app.domain.models import DataStatus, DecisionRequest, RiskAssessment
from app.policy.confidence import near_threshold
from app.policy.loader import Policy


def escalation_reasons(
    payload: DecisionRequest,
    assessment: RiskAssessment | None,
    consistency_errors: list[str],
    confidence: float,
    policy: Policy,
) -> list[str]:
    reasons = list(consistency_errors)
    if assessment is None:
        reasons.append("missing_risk_assessment")
        return reasons
    if payload.quality_summary.status != DataStatus.FRESH:
        reasons.append("evidence_quality_not_fresh")
    if (
        assessment.uncertainty is not None
        and assessment.uncertainty >= policy.thresholds.max_uncertainty
    ):
        reasons.append("high_risk_uncertainty")
    if near_threshold(assessment, policy):
        reasons.append("risk_near_policy_threshold")
    if confidence < policy.thresholds.minimum_confidence:
        reasons.append("low_evidence_confidence")
    if assessment.risk_level == "UNKNOWN":
        reasons.append("unknown_risk_level")
    return list(dict.fromkeys(reasons))
