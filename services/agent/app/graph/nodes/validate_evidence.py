"""`validate_evidence` node — Phase 4.

Real logic, now that `AgentState.control` has `evidence_retry_count`
(`app/graph/state.py::ControlSection`, added this phase specifically for this node).
"Insufficient" evidence is `app/graph/evidence.evidence_insufficient`: `quality.freshness` is not
`FRESH`, or `quality.quality_flags` has `MISSING` or `INCOMPLETE`.

This node only *counts* attempts — it increments `evidence_retry_count` whenever evidence is
insufficient, unconditionally. The one decision of "is there a retry left" lives entirely in
routing (`app/graph/routing.build_after_validate_evidence`), which compares the now-incremented
count against `Settings.evidence_retry_max`. That split — count here, limit there — is what turns
the graph's one back-edge (`validate_evidence -> build_evidence`) into something that provably
terminates (`docs/diagrams/agent-state.md` §2): the limit is checked in exactly one place, so a
future change to the retry policy cannot accidentally leave a path that never checks it.

Still practically unreachable while `build_evidence` raises `NodeNotImplementedError` (Phase 3/4
blocked on module 04's unpublished `external_data` contract) — real evidence.quality never gets
produced yet, so this node is exercised directly in tests rather than through a full graph run.
"""

from __future__ import annotations

from app.graph.evidence import evidence_insufficient
from app.graph.state import AgentState


async def validate_evidence(state: AgentState) -> dict[str, object]:
    if not evidence_insufficient(state.quality):
        return {}
    return {"control_patch": {"evidence_retry_count": state.control.evidence_retry_count + 1}}
