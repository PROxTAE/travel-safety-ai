from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.models import ActionCode, DecisionReason, DecisionRequest, DecisionResult, RiskAssessment, RiskLevel
from app.policy.loader import Policy


@dataclass(frozen=True)
class Evaluation:
    action: ActionCode
    risk_level: RiskLevel
    confidence: float
    rules_fired: list[str]
    reasons: list[DecisionReason]
    escalation_required: bool
    selected_route_id: UUID | None
    limitations: list[dict[str, str | None]]


def validate_consistency(payload: DecisionRequest) -> list[str]:
    errors: list[str] = []
    if payload.travel_window.ends_at <= payload.travel_window.starts_at:
        errors.append("travel_window_invalid")
    route_ids = {route.route_id for route in payload.route_candidates}
    if not {item.route_id for item in payload.assessments}.issubset(route_ids):
        errors.append("assessment_route_mismatch")
    if any(item.snapshot_id != payload.snapshot_id for item in payload.assessments):
        errors.append("assessment_snapshot_mismatch")
    if payload.selected_route_id and payload.selected_route_id not in route_ids:
        errors.append("selected_route_missing")
    if any(route.closed and route.route_id == payload.selected_route_id for route in payload.route_candidates):
        errors.append("selected_route_closed")
    if any(alert.ends_at and alert.ends_at <= payload.travel_window.starts_at for alert in payload.official_alerts):
        errors.append("expired_official_alert")
    if payload.schema_version != "1.0.0" or payload.contract_version != "1.0.0":
        errors.append("unsupported_contract_version")
    return errors


def _quality_score(payload: DecisionRequest, assessment: RiskAssessment) -> float:
    values = [payload.quality_summary.score, assessment.quality.score]
    score = min((value for value in values if value is not None), default=0.0)
    if assessment.uncertainty is not None:
        score *= 1 - assessment.uncertainty
    return max(0.0, min(1.0, score))


def evaluate(payload: DecisionRequest, policy: Policy) -> Evaluation:
    errors = validate_consistency(payload)
    by_route = {item.route_id: item for item in payload.assessments}
    usable_routes = [route for route in payload.route_candidates if not route.closed and route.route_id in by_route]
    critical_alerts = [alert for alert in payload.official_alerts if alert.official and alert.active and alert.intersects_route and alert.closure]
    escalation = bool(errors)
    if critical_alerts:
        return Evaluation(
            ActionCode.AVOID, RiskLevel.HIGH, 1.0, ["R001_OFFICIAL_CLOSURE"],
            [DecisionReason(code="OFFICIAL_CLOSURE", text="An active official closure intersects the selected travel corridor.", source_ids=[a.source_id for a in critical_alerts])],
            escalation, None, [],
        )

    focus = by_route.get(payload.selected_route_id) if payload.selected_route_id else max(by_route.values(), key=lambda item: item.score, default=None)
    if focus is None:
        return Evaluation(ActionCode.AVOID, RiskLevel.UNKNOWN, 0.0, ["R000_INSUFFICIENT_EVIDENCE"], [DecisionReason(code="INSUFFICIENT_EVIDENCE", text="No usable route risk assessment was provided.")], True, None, [{"code": "NO_RELIABLE_KNOWLEDGE_EVIDENCE", "text": "No usable route assessment is available."}])

    confidence = _quality_score(payload, focus)
    limitations: list[dict[str, str | None]] = []
    if payload.quality_summary.status != "FRESH":
        escalation = True
        code = "STALE_EVIDENCE_USED" if payload.quality_summary.status == "STALE" else "CONFLICTING_SOURCES"
        limitations.append({"code": code, "text": "Evidence quality requires review before travel."})
    if errors:
        return Evaluation(ActionCode.AVOID, RiskLevel.HIGH if focus.score >= policy.thresholds.high_risk_score else RiskLevel.UNKNOWN, min(confidence, 0.25), ["R000_INPUT_INCONSISTENCY"], [DecisionReason(code="CONFLICTING_EVIDENCE", text="Input identifiers or route window are inconsistent; the result is conservative.")], True, None, limitations)

    safer = next((route for route in usable_routes if route.route_id != focus.route_id and by_route[route.route_id].score <= focus.score - policy.thresholds.materially_safer_delta and _quality_score(payload, by_route[route.route_id]) >= policy.thresholds.alternative_min_quality), None)
    if focus.score >= policy.thresholds.high_risk_score and safer is None:
        return Evaluation(ActionCode.AVOID, RiskLevel.HIGH, confidence, ["R002_HIGH_RISK_NO_SAFE_ROUTE"], [DecisionReason(code="ACTIVE_DISASTER_ON_CORRIDOR", text="The selected route has high assessed risk and no materially safer usable alternative.")], True, None, limitations)
    if safer:
        return Evaluation(ActionCode.CHANGE_ROUTE, by_route[safer.route_id].risk_level, confidence, ["R003_MATERIALLY_SAFER_ROUTE"], [DecisionReason(code="ACTIVE_DISASTER_ON_CORRIDOR", text="A materially safer usable route is available.")], escalation, safer.route_id, limitations)

    selected_route = next((route for route in usable_routes if route.route_id == focus.route_id), None)
    if focus.score >= policy.thresholds.delay_risk_score and "LONG_EXPOSURE_WINDOW" in focus.reason_codes and selected_route and selected_route.duration_seconds and selected_route.duration_seconds <= policy.thresholds.max_delay_minutes * 60:
        return Evaluation(ActionCode.DELAY, focus.risk_level, confidence, ["R004_TIME_DEPENDENT_RISK"], [DecisionReason(code="LONG_EXPOSURE_WINDOW", text="Risk is time-dependent and the planned window can be delayed within policy.")], escalation, selected_route.route_id, limitations)
    return Evaluation(ActionCode.NORMAL, focus.risk_level, confidence, ["R005_LOW_RISK_USABLE_EVIDENCE"], [DecisionReason(code="SPARSE_DATA_COVERAGE" if confidence < policy.thresholds.minimum_confidence else "NO_ACTIVE_RESTRICTION", text="No higher-priority safety rule applies to the validated route evidence.")], escalation or confidence < policy.thresholds.minimum_confidence, selected_route.route_id if selected_route else None, limitations)


def build_result(payload: DecisionRequest, policy: Policy, evaluation: Evaluation) -> DecisionResult:
    summaries = {
        ActionCode.NORMAL: "The validated evidence supports continuing the planned route.",
        ActionCode.CHANGE_ROUTE: "A materially safer validated route is available.",
        ActionCode.DELAY: "Delaying within the approved window may reduce the assessed risk.",
        ActionCode.AVOID: "Do not use the affected route while the safety condition remains active.",
    }
    return DecisionResult(
        decision_id=uuid4(), request_id=payload.request_id, snapshot_id=payload.snapshot_id,
        action_code=evaluation.action, risk_level=evaluation.risk_level, confidence=evaluation.confidence,
        selected_route_id=evaluation.selected_route_id, rules_fired=evaluation.rules_fired,
        escalation_required=evaluation.escalation_required, summary=summaries[evaluation.action],
        reasons=evaluation.reasons, limitations=evaluation.limitations,
        versions={"policy": policy.version, "prompt": None, "llm_model": None, "contract": policy.contract_version},
        validation={"schema": True, "citations": True, "locked_action": True}, created_at=datetime.now(UTC),
    )