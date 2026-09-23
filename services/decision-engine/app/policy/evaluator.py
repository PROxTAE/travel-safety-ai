from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.models import (
    ActionCode,
    DecisionReason,
    DecisionRequest,
    DecisionResult,
    RiskAssessment,
    RiskLevel,
)
from app.policy.confidence import evidence_confidence
from app.policy.escalation import escalation_reasons
from app.policy.fallback import localized_reason, localized_summary
from app.policy.loader import Policy


@dataclass(frozen=True)
class RuleTrace:
    rule_id: str
    priority: int
    matched: bool


@dataclass(frozen=True)
class Evaluation:
    action: ActionCode
    risk_level: RiskLevel
    confidence: float
    rules_fired: list[str]
    rules_evaluated: list[RuleTrace]
    reasons: list[DecisionReason]
    escalation_required: bool
    escalation_reasons: list[str]
    selected_route_id: UUID | None
    limitations: list[dict[str, str | None]]


def _score(a: RiskAssessment | None) -> float:
    if a is None or a.score is None:
        if a and a.risk_level == RiskLevel.HIGH:
            return 0.85
        elif a and a.risk_level == RiskLevel.MEDIUM:
            return 0.45
        elif a and a.risk_level == RiskLevel.LOW:
            return 0.15
        return 0.0
    return a.score


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
    if any(
        route.closed and route.route_id == payload.selected_route_id
        for route in payload.route_candidates
    ):
        errors.append("selected_route_closed")
    if any(
        alert.ends_at and alert.ends_at <= payload.travel_window.starts_at
        for alert in payload.official_alerts
    ):
        errors.append("expired_official_alert")
    if payload.schema_version != "1.0.0" or payload.contract_version != "1.0.0":
        errors.append("unsupported_contract_version")
    return errors


def _trace(rules: list[tuple[str, int, bool]]) -> list[RuleTrace]:
    return [
        RuleTrace(rule_id=rule_id, priority=priority, matched=matched)
        for rule_id, priority, matched in sorted(rules, key=lambda item: item[1])
    ]


def _policy_rule_trace(policy: Policy, matched_rule: str | None = None) -> list[RuleTrace]:
    rules = [
        (str(rule["id"]), int(rule["priority"]), str(rule["id"]) == matched_rule)
        for rule in policy.rules
    ]
    return _trace(rules)


def limitation_notices(
    payload: DecisionRequest, focus: RiskAssessment | None, policy: Policy
) -> list[dict[str, str | None]]:
    limitations: list[dict[str, str | None]] = []
    if payload.quality_summary.status != "FRESH":
        limitations.append(
            {
                "code": (
                    "STALE_EVIDENCE_USED"
                    if payload.quality_summary.status == "STALE"
                    else "CONFLICTING_SOURCES"
                ),
                "text": "Evidence quality requires review before travel.",
            }
        )
    return limitations


def evaluate(payload: DecisionRequest, policy: Policy) -> Evaluation:
    """Evaluate decision policy using explicit, deterministic precedence."""
    errors = validate_consistency(payload)
    usable_routes = [route for route in payload.route_candidates if not route.closed]
    by_route = {assessment.route_id: assessment for assessment in payload.assessments}
    focus = (
        by_route.get(payload.selected_route_id)
        if payload.selected_route_id in by_route
        else (payload.assessments[0] if payload.assessments else None)
    )
    confidence = evidence_confidence(payload, focus) if focus else 0.0
    critical_alerts = [
        alert
        for alert in payload.official_alerts
        if alert.active and (alert.closure or alert.intersects_route)
    ]
    escalation = escalation_reasons(payload, focus, errors, confidence, policy)
    limitations = limitation_notices(payload, focus, policy)

    if critical_alerts:
        return Evaluation(
            ActionCode.AVOID,
            RiskLevel.HIGH,
            min(confidence, 0.5),
            ["R001_OFFICIAL_HAZARD_OVERRIDE"],
            _trace([("R001_OFFICIAL_HAZARD_OVERRIDE", 0, True)]),
            [
                DecisionReason(
                    code="OFFICIAL_CLOSURE",
                    text="An active official closure intersects the selected travel corridor.",
                    source_ids=[alert.source_id for alert in critical_alerts],
                )
            ],
            bool(escalation),
            escalation,
            None,
            limitations,
        )
    if focus is None:
        return Evaluation(
            ActionCode.AVOID,
            RiskLevel.UNKNOWN,
            0.0,
            ["R000_INSUFFICIENT_EVIDENCE"],
            _trace([("R000_INSUFFICIENT_EVIDENCE", 0, True)]),
            [
                DecisionReason(
                    code="INSUFFICIENT_EVIDENCE",
                    text="No usable route risk assessment was provided.",
                )
            ],
            True,
            escalation or ["missing_risk_assessment"],
            None,
            [
                {
                    "code": "NO_RELIABLE_KNOWLEDGE_EVIDENCE",
                    "text": "No usable route assessment is available.",
                }
            ],
        )
    if errors:
        return Evaluation(
            ActionCode.AVOID,
            RiskLevel.HIGH
            if _score(focus) >= policy.thresholds.high_risk_score
            else RiskLevel.UNKNOWN,
            min(confidence, 0.25),
            ["R000_INPUT_INCONSISTENCY"],
            _trace([("R000_INPUT_INCONSISTENCY", 0, True)]),
            [
                DecisionReason(
                    code="CONFLICTING_EVIDENCE",
                    text=(
                        "Input identifiers or route window are inconsistent; "
                        "the result is conservative."
                    ),
                )
            ],
            True,
            escalation,
            None,
            limitations,
        )

    safer = next(
        (
            route
            for route in usable_routes
            if route.route_id != focus.route_id
            and _score(by_route.get(route.route_id))
            <= _score(focus) - policy.thresholds.materially_safer_delta
            and evidence_confidence(payload, by_route[route.route_id])
            >= policy.thresholds.alternative_min_quality
        ),
        None,
    )
    if _score(focus) >= policy.thresholds.high_risk_score and safer is None:
        action = ActionCode.AVOID
        rule = "R002_HIGH_RISK_NO_SAFE_ROUTE"
        risk_level = RiskLevel.HIGH
        reason = DecisionReason(
            code="ACTIVE_DISASTER_ON_CORRIDOR",
            text=(
                "The selected route has high assessed risk and no materially "
                "safer usable alternative."
            ),
        )
        selected_id = None
    elif safer:
        action = ActionCode.CHANGE_ROUTE
        rule = "R003_MATERIALLY_SAFER_ROUTE"
        risk_level = by_route[safer.route_id].risk_level
        reason = DecisionReason(
            code="ACTIVE_DISASTER_ON_CORRIDOR", text="A materially safer usable route is available."
        )
        selected_id = safer.route_id
    else:
        selected_route = next(
            (route for route in usable_routes if route.route_id == focus.route_id), None
        )
        delayed = (
            _score(focus) >= policy.thresholds.delay_risk_score
            and "LONG_EXPOSURE_WINDOW" in focus.reason_codes
            and selected_route is not None
            and selected_route.duration_seconds is not None
            and selected_route.duration_seconds <= policy.thresholds.max_delay_minutes * 60
        )
        action = ActionCode.DELAY if delayed else ActionCode.NORMAL
        rule = "R004_TIME_DEPENDENT_RISK" if delayed else "R005_LOW_RISK_USABLE_EVIDENCE"
        risk_level = focus.risk_level
        reason = DecisionReason(
            code="LONG_EXPOSURE_WINDOW"
            if delayed
            else (
                "SPARSE_DATA_COVERAGE"
                if confidence < policy.thresholds.minimum_confidence
                else "NO_ACTIVE_RESTRICTION"
            ),
            text="Risk is time-dependent and the planned window can be delayed within policy."
            if delayed
            else "No higher-priority safety rule applies to the validated route evidence.",
        )
        selected_id = selected_route.route_id if selected_route else None

    return Evaluation(
        action,
        risk_level,
        confidence,
        [rule],
        _policy_rule_trace(policy, rule),
        [reason],
        bool(escalation),
        escalation,
        selected_id,
        limitations,
    )


def build_result(
    payload: DecisionRequest, policy: Policy, evaluation: Evaluation
) -> DecisionResult:
    return DecisionResult(
        decision_id=uuid4(),
        request_id=payload.request_id,
        snapshot_id=payload.snapshot_id,
        action_code=evaluation.action,
        risk_level=evaluation.risk_level,
        confidence=evaluation.confidence,
        selected_route_id=evaluation.selected_route_id,
        rules_fired=evaluation.rules_fired,
        escalation_required=evaluation.escalation_required,
        summary=localized_summary(evaluation.action, payload.locale),
        reasons=[localized_reason(reason, payload.locale) for reason in evaluation.reasons],
        limitations=evaluation.limitations,
        versions={
            "policy": policy.version,
            "prompt": None,
            "llm_model": None,
            "contract": policy.contract_version,
        },
        validation={"schema": True, "citations": True, "locked_action": True},
        created_at=datetime.now(UTC),
    )
