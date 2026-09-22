"""`validate_input` node (docs/diagrams/agent-state.md node table, stage `VALIDATING`).

The request has already passed Pydantic validation before it reached this graph: module 02 built
and validated the `TravelRequest`, and `AgentState` itself does not construct without a valid one.
This node is not re-running field-level checks the type system already guarantees — it checks the
one thing types cannot: that the identity envelope actually matches the request it wraps. A
mismatch here would mean two different requests were merged into a single run, which no
downstream node could safely recover from, so it fails closed rather than continuing.
"""

from __future__ import annotations

from app.graph.state import AgentState, RunStatus


async def validate_input(state: AgentState) -> dict[str, object]:
    identity = state.identity
    request = state.input.travel_request
    mismatched = identity.request_id != request.request_id or identity.trip_id != request.trip_id
    if mismatched:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "VALIDATION_ERROR"],
            }
        }
    return {}
