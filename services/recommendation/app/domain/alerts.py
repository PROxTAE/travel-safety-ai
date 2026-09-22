from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.recommendation import RecommendationResponse

DeliveryChannel = Literal["IN_APP", "EMAIL", "SMS", "PUSH"]
SeverityLevel = Literal["INFO", "MINOR", "MODERATE", "SEVERE", "EXTREME", "UNKNOWN"]

SEVERITY_RANKS: dict[str, int] = {
    "INFO": 1,
    "LOW": 1,
    "MINOR": 2,
    "MODERATE": 3,
    "MEDIUM": 3,
    "SEVERE": 4,
    "HIGH": 4,
    "EXTREME": 5,
    "CRITICAL": 5,
    "UNKNOWN": 0,
}

ACTION_RANKS: dict[str, int] = {
    "NORMAL": 1,
    "DELAY": 2,
    "CHANGE_ROUTE": 3,
    "AVOID": 4,
}

# Cooldown durations by severity
COOLDOWN_DURATIONS: dict[str, timedelta] = {
    "INFO": timedelta(minutes=60),
    "LOW": timedelta(minutes=60),
    "MINOR": timedelta(minutes=30),
    "MODERATE": timedelta(minutes=15),
    "MEDIUM": timedelta(minutes=15),
    "SEVERE": timedelta(minutes=5),
    "HIGH": timedelta(minutes=5),
    "EXTREME": timedelta(minutes=2),
    "CRITICAL": timedelta(minutes=2),
    "UNKNOWN": timedelta(minutes=15),
}


class MeaningfulChangeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_meaningful: bool
    reasons: list[str] = Field(default_factory=list)
    previous_action: str | None = None
    new_action: str
    previous_risk: str | None = None
    new_risk: str
    is_escalation: bool = False
    cooldown_bypass_required: bool = False


class AlertSubscription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subscription_id: str
    user_id: str
    trip_id: str
    channel: DeliveryChannel
    destination: str | None = None
    consent_id: str
    status: Literal["ACTIVE", "PAUSED", "CANCELLED", "EXPIRED"] = "ACTIVE"
    min_severity: SeverityLevel = "MODERATE"
    cooldown_until: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cancelled_at: datetime | None = None


def compute_event_hash(
    trip_id: str,
    action_code: str,
    risk_level: str,
    alert_ids: list[str],
    version: str = "1.0.0",
) -> str:
    """Computes a deterministic unique hash for an alert event to prevent duplicate deliveries."""
    sorted_alert_ids = sorted(alert_ids)
    raw = f"{trip_id}:{action_code}:{risk_level}:{','.join(sorted_alert_ids)}:{version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def detect_meaningful_change(
    prev: RecommendationResponse | None,
    curr: RecommendationResponse,
) -> MeaningfulChangeResult:
    """Compares previous and current recommendations to detect meaningful safety changes."""
    reasons: list[str] = []
    is_escalation = False
    cooldown_bypass = False

    if prev is None:
        # Initial assessment is always delivered if risk is MODERATE or higher
        curr_risk_rank = SEVERITY_RANKS.get(curr.risk_level, 0)
        return MeaningfulChangeResult(
            is_meaningful=curr_risk_rank >= SEVERITY_RANKS["MODERATE"]
            or curr.action_code != "NORMAL",
            reasons=["INITIAL_ASSESSMENT"],
            previous_action=None,
            new_action=curr.action_code,
            previous_risk=None,
            new_risk=curr.risk_level,
            is_escalation=curr.action_code in ("CHANGE_ROUTE", "AVOID"),
            cooldown_bypass_required=False,
        )

    # 1. Action change
    prev_action_rank = ACTION_RANKS.get(prev.action_code, 0)
    curr_action_rank = ACTION_RANKS.get(curr.action_code, 0)
    if curr.action_code != prev.action_code:
        reasons.append(f"ACTION_CHANGED: {prev.action_code} -> {curr.action_code}")
        if curr_action_rank > prev_action_rank:
            is_escalation = True
            cooldown_bypass = True

    # 2. Risk level increase
    prev_risk_rank = SEVERITY_RANKS.get(prev.risk_level, 0)
    curr_risk_rank = SEVERITY_RANKS.get(curr.risk_level, 0)
    if curr_risk_rank > prev_risk_rank:
        reasons.append(f"RISK_ESCALATED: {prev.risk_level} -> {curr.risk_level}")
        is_escalation = True
        cooldown_bypass = True
    elif curr_risk_rank < prev_risk_rank and prev_risk_rank >= SEVERITY_RANKS["HIGH"]:
        reasons.append(f"RISK_DE_ESCALATED: {prev.risk_level} -> {curr.risk_level}")

    # 3. New severe alerts
    prev_alert_ids = {a.event_id for a in prev.alerts}
    curr_alert_ids = {a.event_id for a in curr.alerts}
    new_alerts = curr_alert_ids - prev_alert_ids
    if new_alerts:
        reasons.append(f"NEW_HAZARDS_DETECTED: {len(new_alerts)} new hazard(s)")
        # Check if any new alert is SEVERE or EXTREME
        severe_new = any(
            a.event_id in new_alerts and a.severity in ("SEVERE", "EXTREME") for a in curr.alerts
        )
        if severe_new:
            is_escalation = True
            cooldown_bypass = True

    # 4. Primary route closure
    prev_closed = bool(
        prev.primary_route
        and prev.primary_route.exposure
        and prev.primary_route.exposure.get("closed")
    )
    curr_closed = bool(
        curr.primary_route
        and curr.primary_route.exposure
        and curr.primary_route.exposure.get("closed")
    )
    if curr_closed and not prev_closed:
        reasons.append("PRIMARY_ROUTE_CLOSED")
        is_escalation = True
        cooldown_bypass = True

    # 5. Safer alternative became available
    if prev.action_code == "AVOID" and curr.action_code == "CHANGE_ROUTE" and curr.primary_route:
        reasons.append("SAFER_ROUTE_AVAILABLE")

    is_meaningful = len(reasons) > 0
    return MeaningfulChangeResult(
        is_meaningful=is_meaningful,
        reasons=reasons,
        previous_action=prev.action_code,
        new_action=curr.action_code,
        previous_risk=prev.risk_level,
        new_risk=curr.risk_level,
        is_escalation=is_escalation,
        cooldown_bypass_required=cooldown_bypass,
    )


def should_deliver_notification(
    subscription: AlertSubscription,
    change_result: MeaningfulChangeResult,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    """Evaluates whether an alert should be delivered.
    Checks consent status, severity threshold, and cooldown.
    """
    if subscription.status != "ACTIVE":
        return False, f"Subscription status is {subscription.status}"

    current_time = now or datetime.now(UTC)
    if subscription.expires_at and subscription.expires_at < current_time:
        return False, "Subscription expired"

    # Check minimum severity threshold
    sub_min_rank = SEVERITY_RANKS.get(subscription.min_severity, 3)
    curr_risk_rank = SEVERITY_RANKS.get(change_result.new_risk, 0)
    if curr_risk_rank < sub_min_rank and not change_result.is_escalation:
        return (
            False,
            f"Risk {change_result.new_risk} below min severity {subscription.min_severity}",
        )

    # Check cooldown
    if subscription.cooldown_until and subscription.cooldown_until > current_time:
        # CRITICAL INVARIANT: Escalation to higher severity ALWAYS bypasses cooldown
        if change_result.cooldown_bypass_required:
            return True, "Cooldown bypassed due to higher severity escalation"
        return False, f"In cooldown until {subscription.cooldown_until.isoformat()}"

    return True, None
