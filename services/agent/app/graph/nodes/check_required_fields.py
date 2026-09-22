"""`check_required_fields` node.

Enforces the one requirement the shared contract fixes for every recommendation-producing
request — `confirmed_by_user=true` on both `origin` and `destination`
(00_API_AND_DATA_CONTRACTS.md §3.1) — plus the per-`Intent` extras from
`docs/intent-and-required-fields.md` §2 (`app/intent/required_fields.py`), now that
`classify_intent` (Phase 2) has set `input.intent` before this node runs. Setting
`control_patch.status = NEEDS_INPUT` lives here, next to the field that drives it, rather than in
a separate node — the routing table (`app/graph/routing.after_check_required_fields`) reads
`missing_fields`/`status` back out, not the other way around.
"""

from __future__ import annotations

from app.graph.state import AgentState, RunStatus
from app.intent.required_fields import missing_fields_for_intent


async def check_required_fields(state: AgentState) -> dict[str, object]:
    request = state.input.travel_request
    missing: list[str] = []
    if not request.origin.confirmed_by_user:
        missing.append("origin.confirmed_by_user")
    if not request.destination.confirmed_by_user:
        missing.append("destination.confirmed_by_user")
    if state.input.intent is not None:
        missing.extend(missing_fields_for_intent(state.input.intent, state.input))

    update: dict[str, object] = {
        "input": state.input.model_copy(update={"missing_fields": missing})
    }
    if missing:
        update["control_patch"] = {"status": RunStatus.NEEDS_INPUT}
    return update
