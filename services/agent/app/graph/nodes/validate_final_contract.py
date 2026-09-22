"""`validate_final_contract` node.

Real, phase-independent logic: a run may only leave this node toward `finalize` if it actually
carries a `result.recommendation_id` from Module 08 — never on the strength of an earlier node
merely not having failed. Each service's own response shape is validated by its typed tool client
(Phase 3); this is the last gate before a terminal status is assigned.
"""

from __future__ import annotations

from app.graph.state import AgentState, RunStatus


async def validate_final_contract(state: AgentState) -> dict[str, object]:
    if state.result.recommendation_id is None:
        return {
            "control_patch": {
                "status": RunStatus.FAILED,
                "errors": [*state.control.errors, "POLICY_VALIDATION_FAILED"],
            }
        }
    return {}
