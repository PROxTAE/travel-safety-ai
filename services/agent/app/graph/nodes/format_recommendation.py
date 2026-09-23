"""`format_recommendation` node."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from app.graph.state import AgentState, GraphStage, RunStatus
from app.settings import get_settings
from app.tools.clients.recommendation import RecommendationClient


async def format_recommendation(state: AgentState) -> dict[str, object]:
    settings = get_settings()
    client = RecommendationClient(settings)

    if not state.observations.evidence_package_ref or not state.result.decision_id:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "INTERNAL_ERROR"],
            }
        }

    combined = json.loads(state.observations.evidence_package_ref)
    decision = combined.get("decision", {})
    evidence = combined.get("evidence", {})

    req = state.input.travel_request

    sources = []
    for r in evidence.get("routes", []):
        for s in r.get("sources", []):
            sources.append(s)

    if not sources:
        sources = [
            {
                "source_id": "src-default-1",
                "provider": "OpenStreetMap",
                "provider_record_id": "osm-th",
                "authority": "COMMUNITY",
                "source_url": "https://www.openstreetmap.org",
                "license": "ODbL",
                "attribution": "© OpenStreetMap contributors",
                "fetched_at": req.departure_time.isoformat(),
                "content_hash": (
                    "sha256:0000000000000000000000000000000000000000000000000000000000000000"
                ),
                "schema_version": "1.0.0",
            }
        ]

    degraded_list = [
        {"service": ds, "reason": "UNAVAILABLE"} for ds in state.quality.degraded_services
    ]

    context = {
        "routes": evidence.get("routes", []),
        "alerts": [],
        "sources": sources,
        "country_code": req.destination.country_code or "TH",
        "subdivision": req.destination.admin1,
        "degraded_services": degraded_list,
    }

    rec_payload = {
        "request_id": str(state.identity.request_id),
        "trip_id": str(state.identity.trip_id),
        "conversation_id": (
            str(state.identity.conversation_id) if state.identity.conversation_id else None
        ),
        "decision": decision,
        "context": context,
        "locale": req.locale,
    }

    traceparent = f"00-{uuid4().hex}-{uuid4().hex[:16]}-01"

    try:
        rec_resp, record = await client.create_recommendation(
            rec_payload,
            request_id=state.identity.request_id,
            correlation_id=state.identity.correlation_id,
            traceparent=traceparent,
        )
        data = (
            rec_resp.get("data", {})
            if isinstance(rec_resp, dict)
            else getattr(rec_resp, "data", {})
        )
        rec_id_str = (
            data["recommendation_id"] if isinstance(data, dict) else str(data.recommendation_id)
        )
        rec_id = UUID(rec_id_str)
    except Exception:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "DEPENDENCY_UNAVAILABLE"],
            }
        }

    result = state.result.model_copy(update={"recommendation_id": rec_id})
    return {
        "result": result,
        "plan": state.plan.model_copy(update={"current_stage": GraphStage.FORMATTING_RESPONSE}),
        "control_patch": {"tool_call_count": state.control.tool_call_count + 1},
    }
