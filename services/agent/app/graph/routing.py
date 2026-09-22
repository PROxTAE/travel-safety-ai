"""Conditional-edge decisions for the agent graph.

Kept separate from `builder.py`, and pure and synchronous, so each branch can be unit tested
without compiling or running the graph. Every function mirrors one branch point in
docs/diagrams/agent-state.md §2 "Graph flow" and returns one of the string keys registered in that
edge's `path_map` in `builder.py` — never a node name directly, so the node-name-to-key mapping
stays declared in exactly one place.
"""

from __future__ import annotations

from collections.abc import Callable

from app.graph.evidence import evidence_insufficient
from app.graph.state import AgentState, Intent, RunStatus
from app.settings import Settings

#: Statuses `guard_node` (app/budgets) may have already assigned before a node's own body ran —
#: cancellation or a budget/deadline stop. Distinct from `NEEDS_INPUT`, which a node sets itself.
_GUARD_STOPPED = {RunStatus.CANCELLED, RunStatus.FAILED}


def after_guarded(state: AgentState) -> str:
    """Generic branch used after every node with no branch of its own: the budget/cancel guard
    may have ended the run before the node body executed at all."""
    return "stopped" if state.control.status in _GUARD_STOPPED else "continue"


def after_classify_intent(state: AgentState) -> str:
    """`EMERGENCY` takes the shortcut (`app/graph/nodes/emergency_shortcut.py`) straight past
    `check_required_fields`/`fetch_external_data`/`integrate_data`/`build_evidence` — the plan's
    "ส่งทางลัดไปข้อมูลฉุกเฉิน" requirement, Phase 0 step 3."""
    if state.control.status in _GUARD_STOPPED:
        return "stopped"
    if state.input.intent is Intent.EMERGENCY:
        return "emergency"
    return "continue"


def after_check_required_fields(state: AgentState) -> str:
    if state.control.status is RunStatus.NEEDS_INPUT:
        return "needs_input"
    return after_guarded(state)


def after_validate_final_contract(state: AgentState) -> str:
    return "invalid" if state.control.status is RunStatus.FAILED else "valid"


def build_after_validate_evidence(settings: Settings) -> Callable[[AgentState], str]:
    """Needs `Settings.evidence_retry_max`, so — like `classify_intent`'s node factory — this is
    built once per graph rather than being a bare module-level function."""

    def after_validate_evidence(state: AgentState) -> str:
        if state.control.status in _GUARD_STOPPED:
            return "stopped"
        if not evidence_insufficient(state.quality):
            return "continue"
        if state.control.evidence_retry_count <= settings.evidence_retry_max:
            return "retry"
        return "escalate"

    return after_validate_evidence
