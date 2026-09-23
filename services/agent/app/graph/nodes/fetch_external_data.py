"""`fetch_external_data` node."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

from app.graph.state import AgentState, GraphStage
from app.settings import get_settings
from app.tools.clients.external_data import ExternalDataClient


async def fetch_external_data(state: AgentState) -> dict[str, object]:
    settings = get_settings()
    client = ExternalDataClient(settings)

    req = state.input.travel_request
    orig_coords = req.origin.coordinates.coordinates
    dest_coords = req.destination.coordinates.coordinates
    mode_str = req.travel_modes[0].value if req.travel_modes else "CAR"
    start_dt = req.departure_time
    end_dt = req.return_time or (start_dt + timedelta(hours=6))

    query_payload = {
        "waypoints": [[orig_coords[0], orig_coords[1]], [dest_coords[0], dest_coords[1]]],
        "mode": mode_str,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "language": req.locale[:2] if req.locale else "th",
        "alternatives": 2,
        "deadline_seconds": 25.0,
    }

    traceparent = f"00-{uuid4().hex}-{uuid4().hex[:16]}-01"

    try:
        data_resp, record = await client.query_context(
            query_payload,
            request_id=state.identity.request_id,
            correlation_id=state.identity.correlation_id,
            traceparent=traceparent,
        )
        ext_data = data_resp.get("data", {})
        degraded = data_resp.get("meta", {}).get("degraded_services", [])
    except Exception as exc:
        ext_data = {
            "weather": [],
            "disaster_events": [],
            "routes": [],
            "transport": [],
            "places": [],
        }
        degraded = [{"service": "external-data", "reason": str(exc)}]

    obs = state.observations.model_copy(update={"external_context_ref": json.dumps(ext_data)})
    quality = state.quality.model_copy(
        update={"degraded_services": [str(d) for d in degraded] if degraded else []}
    )

    return {
        "observations": obs,
        "quality": quality,
        "plan": state.plan.model_copy(update={"current_stage": GraphStage.FETCHING_EXTERNAL_DATA}),
        "control_patch": {"tool_call_count": state.control.tool_call_count + 1},
    }
