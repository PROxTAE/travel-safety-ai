from pathlib import Path
from uuid import UUID, uuid4

from hypothesis import given
from hypothesis import strategies as st

from app.domain.models import DecisionRequest
from app.policy.evaluator import build_result, evaluate, validate_consistency
from app.policy.loader import load_policy

POLICY, _ = load_policy(Path(__file__).parents[1] / "policies/v1/decision-table.yaml")
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000001")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000002")
ROUTE_A = UUID("00000000-0000-0000-0000-000000000003")
ROUTE_B = UUID("00000000-0000-0000-0000-000000000004")


def make_request(
    score_a: float, score_b: float | None = None, **overrides: object
) -> DecisionRequest:
    routes = [
        {
            "route_id": str(ROUTE_A),
            "duration_seconds": 3600,
            "quality": {"status": "FRESH", "score": 0.95},
        }
    ]
    assessments = [
        {
            "snapshot_id": str(SNAPSHOT_ID),
            "route_id": str(ROUTE_A),
            "score": score_a,
            "risk_level": "HIGH" if score_a >= 0.65 else "LOW",
            "quality": {"status": "FRESH", "score": 0.95},
            "reason_codes": [],
        }
    ]
    if score_b is not None:
        routes.append(
            {
                "route_id": str(ROUTE_B),
                "duration_seconds": 4000,
                "quality": {"status": "FRESH", "score": 0.95},
            }
        )
        assessments.append(
            {
                "snapshot_id": str(SNAPSHOT_ID),
                "route_id": str(ROUTE_B),
                "score": score_b,
                "risk_level": "LOW",
                "quality": {"status": "FRESH", "score": 0.95},
                "reason_codes": [],
            }
        )
    data = {
        "request_id": str(REQUEST_ID),
        "snapshot_id": str(SNAPSHOT_ID),
        "schema_version": "1.0.0",
        "feature_schema_version": "1.0.0",
        "travel_window": {
            "starts_at": "2026-09-22T09:00:00Z",
            "ends_at": "2026-09-22T10:00:00Z",
            "timezone": "UTC",
        },
        "route_candidates": routes,
        "assessments": assessments,
        "quality_summary": {"status": "FRESH", "score": 0.95},
        "selected_route_id": str(ROUTE_A),
    }
    data.update(overrides)
    return DecisionRequest.model_validate(data)


def test_official_closure_has_priority_over_low_model_score() -> None:
    payload = make_request(0.1, official_alerts=[{"source_id": "official-1", "closure": True}])
    result = build_result(payload, POLICY, evaluate(payload, POLICY))
    assert result.action_code == "AVOID"
    assert result.rules_fired == ["R001_OFFICIAL_CLOSURE"]


def test_materially_safer_route_is_selected() -> None:
    payload = make_request(0.8, 0.5)
    result = build_result(payload, POLICY, evaluate(payload, POLICY))
    assert result.action_code == "CHANGE_ROUTE"
    assert result.selected_route_id == ROUTE_B


def test_inconsistent_snapshot_is_conservative_and_escalates() -> None:
    payload = make_request(
        0.1,
        assessments=[
            {
                "snapshot_id": str(uuid4()),
                "route_id": str(ROUTE_A),
                "score": 0.1,
                "risk_level": "LOW",
                "quality": {"status": "FRESH", "score": 0.95},
            }
        ],
    )
    assert "assessment_snapshot_mismatch" in validate_consistency(payload)
    result = build_result(payload, POLICY, evaluate(payload, POLICY))
    assert result.action_code == "AVOID"
    assert result.escalation_required is True


def test_quality_cannot_raise_confidence() -> None:
    fresh = make_request(0.1)
    stale = make_request(0.1, quality_summary={"status": "STALE", "score": 0.2})
    assert evaluate(stale, POLICY).confidence <= evaluate(fresh, POLICY).confidence


def test_high_risk_boundary_is_inclusive() -> None:
    at_boundary = evaluate(make_request(POLICY.thresholds.high_risk_score), POLICY)
    above_boundary = evaluate(make_request(POLICY.thresholds.high_risk_score + 0.001), POLICY)
    assert at_boundary.action == "AVOID"
    assert above_boundary.action == "AVOID"


def test_materially_safer_delta_boundary_is_inclusive() -> None:
    evaluation = evaluate(make_request(0.8, 0.8 - POLICY.thresholds.materially_safer_delta), POLICY)
    assert evaluation.action == "CHANGE_ROUTE"
    assert evaluation.selected_route_id == ROUTE_B


def test_rule_trace_is_priority_ordered_and_single_match() -> None:
    evaluation = evaluate(make_request(0.8, 0.5), POLICY)
    assert [trace.priority for trace in evaluation.rules_evaluated] == [1, 2, 3, 4, 5]
    assert [trace.rule_id for trace in evaluation.rules_evaluated if trace.matched] == [
        "R003_MATERIALLY_SAFER_ROUTE"
    ]


def test_thai_fallback_is_deterministic() -> None:
    result = build_result(
        make_request(0.1, locale="th-TH"),
        POLICY,
        evaluate(make_request(0.1, locale="th-TH"), POLICY),
    )
    assert result.summary.startswith("หลักฐาน")


@st.composite
def valid_scores(draw: st.DrawFn) -> tuple[float, float]:
    return draw(
        st.tuples(
            st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False), st.just(0.0)
        )
    )


@given(valid_scores())
def test_increasing_risk_does_not_weaken_action(scores: tuple[float, float]) -> None:
    low_score, _ = scores
    higher_score = min(1.0, low_score + 0.2)
    action_rank = {"NORMAL": 0, "DELAY": 1, "CHANGE_ROUTE": 2, "AVOID": 3}
    low_action = evaluate(make_request(low_score), POLICY).action.value
    high_action = evaluate(make_request(higher_score), POLICY).action.value
    assert action_rank[high_action] >= action_rank[low_action]
