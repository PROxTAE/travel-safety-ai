from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.domain.alerts import (
    AlertSubscription,
    compute_event_hash,
    detect_meaningful_change,
    should_deliver_notification,
)
from app.domain.recommendation import (
    DisasterEvent,
    Freshness,
    RecommendationResponse,
    ResponseVersions,
    RouteCandidate,
)


def make_dummy_recommendation(
    action: str = "NORMAL",
    risk: str = "LOW",
    alerts: list[DisasterEvent] | None = None,
    primary_route_closed: bool = False,
) -> RecommendationResponse:
    now = datetime.now(UTC)
    route = RouteCandidate(
        route_id=str(uuid.uuid4()),
        label="RECOMMENDED" if action != "AVOID" else "ORIGINAL",
        exposure={"closed": primary_route_closed},
        risk_level=risk,
    )
    return RecommendationResponse(
        recommendation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        trip_id=str(uuid.uuid4()),
        status="COMPLETED",
        action_code=action,  # type: ignore[arg-type]
        risk_level=risk,  # type: ignore[arg-type]
        confidence=0.9,
        short_summary="Summary",
        primary_route=route,
        alerts=alerts or [],
        sources=[],
        freshness=Freshness(fetched_at=now),
        versions=ResponseVersions(),
        created_at=now,
    )


def test_detect_meaningful_change_action_escalation() -> None:
    prev = make_dummy_recommendation(action="NORMAL", risk="LOW")
    curr = make_dummy_recommendation(action="CHANGE_ROUTE", risk="MEDIUM")

    res = detect_meaningful_change(prev, curr)
    assert res.is_meaningful is True
    assert res.is_escalation is True
    assert res.cooldown_bypass_required is True
    assert any("ACTION_CHANGED" in r for r in res.reasons)


def test_detect_meaningful_change_new_hazard_and_closure() -> None:
    prev = make_dummy_recommendation(action="NORMAL", risk="LOW")
    hazard = DisasterEvent(
        event_id="alert-flood-1",
        event_type="FLOOD",
        title="Flash Flood on Route 1",
        severity="SEVERE",
    )
    curr = make_dummy_recommendation(
        action="AVOID",
        risk="HIGH",
        alerts=[hazard],
        primary_route_closed=True,
    )

    res = detect_meaningful_change(prev, curr)
    assert res.is_meaningful is True
    assert res.is_escalation is True
    assert res.cooldown_bypass_required is True
    assert any("PRIMARY_ROUTE_CLOSED" in r for r in res.reasons)


def test_no_meaningful_change_identical_assessment() -> None:
    prev = make_dummy_recommendation(action="NORMAL", risk="LOW")
    curr = make_dummy_recommendation(action="NORMAL", risk="LOW")

    res = detect_meaningful_change(prev, curr)
    assert res.is_meaningful is False
    assert len(res.reasons) == 0


def test_cooldown_suppression_and_escalation_bypass() -> None:
    now = datetime.now(UTC)
    future_cooldown = now + timedelta(minutes=20)

    sub = AlertSubscription(
        subscription_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        trip_id=str(uuid.uuid4()),
        channel="IN_APP",
        consent_id=str(uuid.uuid4()),
        status="ACTIVE",
        min_severity="MODERATE",
        cooldown_until=future_cooldown,
    )

    # 1. Same severity during cooldown -> Suppressed
    prev = make_dummy_recommendation(action="NORMAL", risk="MEDIUM")
    curr = make_dummy_recommendation(action="NORMAL", risk="MEDIUM")
    curr.short_summary = "Minor wording update"
    # Even if meaningful flag set artificially
    change_res = detect_meaningful_change(prev, curr)
    change_res.is_meaningful = True
    change_res.cooldown_bypass_required = False
    can_deliver, reason = should_deliver_notification(sub, change_res, now)
    assert can_deliver is False
    assert "cooldown" in str(reason).lower()

    # 2. Higher severity escalation during cooldown -> CRITICAL INVARIANT: NEVER SUPPRESSED
    escalated_prev = make_dummy_recommendation(action="NORMAL", risk="MEDIUM")
    escalated_curr = make_dummy_recommendation(action="AVOID", risk="HIGH")
    escalation_change = detect_meaningful_change(escalated_prev, escalated_curr)

    assert escalation_change.cooldown_bypass_required is True
    can_deliver_escalated, _ = should_deliver_notification(sub, escalation_change, now)
    assert can_deliver_escalated is True


def test_event_hash_determinism() -> None:
    trip_id = str(uuid.uuid4())
    h1 = compute_event_hash(trip_id, "CHANGE_ROUTE", "HIGH", ["alert-2", "alert-1"])
    h2 = compute_event_hash(trip_id, "CHANGE_ROUTE", "HIGH", ["alert-1", "alert-2"])
    assert h1 == h2
    assert len(h1) == 64
