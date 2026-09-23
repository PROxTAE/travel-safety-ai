"""`make_decision` node."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID, uuid4

from app.graph.state import AgentState, GraphStage, RunStatus
from app.settings import get_settings
from app.tools.clients.decision_engine import DecisionEngineClient


async def make_decision(state: AgentState) -> dict[str, object]:
    settings = get_settings()
    client = DecisionEngineClient(settings)

    if not state.observations.evidence_package_ref or not state.observations.snapshot_id:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "INTERNAL_ERROR"],
            }
        }

    ev_data = json.loads(state.observations.evidence_package_ref)
    req = state.input.travel_request
    departure = req.departure_time
    return_time = req.return_time or (departure + timedelta(hours=6))

    routes = ev_data.get("routes", [])
    sanitized_routes = []
    for r in routes:
        r_copy = dict(r)
        if "duration_seconds" in r_copy and r_copy["duration_seconds"] is not None:
            r_copy["duration_seconds"] = int(round(float(r_copy["duration_seconds"])))
        if "transfers" in r_copy and r_copy["transfers"] is not None:
            r_copy["transfers"] = int(r_copy["transfers"])
        sanitized_routes.append(r_copy)

    assessments = ev_data.get("assessments", [])

    dec_payload = {
        "request_id": str(state.identity.request_id),
        "snapshot_id": str(state.observations.snapshot_id),
        "schema_version": "1.0.0",
        "feature_schema_version": "1.0.0",
        "contract_version": state.versions.contract,
        "travel_window": {
            "starts_at": departure.isoformat(),
            "ends_at": return_time.isoformat(),
            "timezone": req.timezone,
        },
        "route_candidates": sanitized_routes,
        "assessments": assessments,
        "official_alerts": [],
        "quality_summary": {
            "status": "FRESH",
            "flags": [],
        },
        "selected_route_id": sanitized_routes[0].get("route_id") if sanitized_routes else None,
        "locale": req.locale,
    }

    traceparent = f"00-{uuid4().hex}-{uuid4().hex[:16]}-01"

    try:
        dec_resp, record = await client.create_decision(
            dec_payload,
            request_id=state.identity.request_id,
            correlation_id=state.identity.correlation_id,
            traceparent=traceparent,
        )
        dec_data = dec_resp if isinstance(dec_resp, dict) else dec_resp.model_dump(mode="json")
        decision_id = UUID(dec_data["decision_id"])
    except Exception:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "DEPENDENCY_UNAVAILABLE"],
            }
        }

    combined = {
        "evidence": ev_data,
        "decision": dec_data,
    }
    obs = state.observations.model_copy(update={"evidence_package_ref": json.dumps(combined)})
    result = state.result.model_copy(update={"decision_id": decision_id})
    return {
        "observations": obs,
        "result": result,
        "plan": state.plan.model_copy(update={"current_stage": GraphStage.MAKING_DECISION}),
        "control_patch": {"tool_call_count": state.control.tool_call_count + 1},
    }
