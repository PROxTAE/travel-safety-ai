"""`finalize` node — the only node allowed to set a `COMPLETED`/`PARTIAL` terminal status.

Reached only once `validate_final_contract` has confirmed a real `recommendation_id` exists.
Returns `PARTIAL`, not `COMPLETED`, whenever the run recorded any degraded dependency or quality
flag (agent-state.md §4: "provider ล่ม แต่ policy อนุญาตให้ไปต่อ ... PARTIAL") — a full-looking result
built on incomplete evidence has to say so rather than claiming full completion.
"""

from __future__ import annotations

from app.graph.state import AgentState, RunStatus


async def finalize(state: AgentState) -> dict[str, object]:
    is_partial = bool(state.quality.degraded_services or state.quality.quality_flags)
    status = RunStatus.PARTIAL if is_partial else RunStatus.COMPLETED
    return {"control_patch": {"status": status}}
