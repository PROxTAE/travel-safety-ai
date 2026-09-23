"""`build_evidence` node."""

from __future__ import annotations

import json
from uuid import uuid4

from app.graph.state import AgentState, GraphStage, RunStatus
from app.settings import get_settings
from app.tools.clients.risk_knowledge import RiskKnowledgeClient
from app.tools.schemas import EvidencePackageRequest


async def build_evidence(state: AgentState) -> dict[str, object]:
    settings = get_settings()
    client = RiskKnowledgeClient(settings)

    if state.observations.snapshot_id is None:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "INTERNAL_ERROR"],
            }
        }

    req = EvidencePackageRequest(
        snapshot_id=state.observations.snapshot_id,
        locale=state.input.travel_request.locale,
        route_ids=[],
    )

    traceparent = f"00-{uuid4().hex}-{uuid4().hex[:16]}-01"

    try:
        resp, record = await client.build_evidence_package(
            req,
            request_id=state.identity.request_id,
            correlation_id=state.identity.correlation_id,
            traceparent=traceparent,
        )
        ev_data = resp.data
    except Exception:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "DEPENDENCY_UNAVAILABLE"],
            }
        }

    obs = state.observations.model_copy(
        update={"evidence_package_ref": json.dumps(ev_data.model_dump(mode="json"))}
    )
    result = state.result.model_copy(
        update={
            "risk_assessments": [a.assessment_id for a in ev_data.assessments],
            "evidence_ids": [e.evidence_id for e in ev_data.evidence],
            "route_ids": [r.route_id for r in ev_data.routes],
        }
    )
    return {
        "observations": obs,
        "result": result,
        "plan": state.plan.model_copy(update={"current_stage": GraphStage.ASSESSING_RISK}),
        "control_patch": {"tool_call_count": state.control.tool_call_count + 1},
    }
