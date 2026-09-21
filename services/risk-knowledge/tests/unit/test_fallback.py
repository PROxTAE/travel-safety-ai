from __future__ import annotations

from copy import deepcopy
from typing import cast
from uuid import UUID

from app.contracts import IntegratedTravelContext, RiskLevel
from app.risk.fallback import assess_with_conservative_fallback
from app.routes.fallback import enforce_hard_constraints_without_ranking

ROUTE_ID = UUID("20000000-0000-4000-8000-000000000001")


def test_missing_model_never_returns_low(snapshot: IntegratedTravelContext) -> None:
    result = assess_with_conservative_fallback(snapshot, [ROUTE_ID])
    assert result[0].risk_level is RiskLevel.UNKNOWN
    assert result[0].score is None
    assert "MODEL_UNAVAILABLE" in result[0].reason_codes
    assert result[0].quality.status == "PARTIAL"


def test_missing_official_alert_features_remain_unknown(
    snapshot_payload: dict[str, object],
) -> None:
    payload = deepcopy(snapshot_payload)
    features = cast(dict[str, object], payload["features"])
    features["corridor_official_closure_active"] = None
    features["corridor_official_evacuation_active"] = None
    features["corridor_extreme_alert_active"] = None

    snapshot = IntegratedTravelContext.model_validate(payload)
    result = assess_with_conservative_fallback(snapshot, [ROUTE_ID])

    assert snapshot.features["corridor_official_closure_active"] is None
    assert snapshot.features["corridor_official_evacuation_active"] is None
    assert snapshot.features["corridor_extreme_alert_active"] is None
    assert result[0].risk_level is RiskLevel.UNKNOWN
    assert "MISSING_CRITICAL_EVIDENCE" in {override.code for override in result[0].safety_overrides}


def test_active_official_extreme_alert_forces_high(
    snapshot_payload: dict[str, object],
) -> None:
    payload = deepcopy(snapshot_payload)
    source = payload["route_candidates"][0]["sources"][0]
    payload["official_alerts"] = [
        {
            "event_id": "test-boundary-extreme-us7000tiib",
            "event_type": "EARTHQUAKE",
            "severity": "EXTREME",
            "official": True,
            "effective_at": "2026-09-20T00:30:00Z",
            "ends_at": "2026-09-20T03:30:00Z",
            "affected_route_ids": [str(ROUTE_ID)],
            "closure": False,
            "evacuation": False,
            "source": source,
            "test_note": "Boundary mutation; not a claim about the captured USGS event severity.",
        }
    ]
    snapshot = IntegratedTravelContext.model_validate(payload)
    result = assess_with_conservative_fallback(snapshot, [ROUTE_ID])
    assert result[0].risk_level is RiskLevel.HIGH
    assert "EXTREME_WARNING_CORRIDOR" in result[0].reason_codes
    assert result[0].score is None


def test_closed_route_is_removed_without_fabricating_recommendation(
    snapshot_payload: dict[str, object],
) -> None:
    payload = deepcopy(snapshot_payload)
    payload["route_candidates"][0]["exposure"]["closed"] = True
    payload["route_candidates"][0]["exposure"]["hard_constraint_codes"] = ["OFFICIAL_CLOSURE"]
    snapshot = IntegratedTravelContext.model_validate(payload)
    usable, unusable = enforce_hard_constraints_without_ranking(
        snapshot.route_candidates, [ROUTE_ID]
    )
    assert usable == []
    assert unusable == [ROUTE_ID]
