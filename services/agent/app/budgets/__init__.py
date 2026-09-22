"""Stop-condition and budget enforcement for the agent graph.

Source of truth: docs/diagrams/agent-state.md §5 "Budget และ stop conditions" — checked, in the
same priority order documented there, before every node runs. `guard_node` is what every node in
`app/graph/builder.py` is wrapped in; it is the single place that increments `control.step_count`
and that a run's stop conditions are evaluated, so "no unlimited loop" is a property of this one
function rather than something each node has to remember to check.

Priority order (first match wins, higher rows override lower ones even when both are true):
    1. `control.cancelled`                                       -> CANCELLED
    2. past `control.deadline_at`                                 -> FAILED / DEPENDENCY_TIMEOUT
    3. step/tool-call/cost ceiling reached                        -> FAILED / AGENT_BUDGET_EXCEEDED

Token-usage and LLM-call ceilings are intentionally not enforced here yet: `AgentState.control` has
no dedicated LLM-call counter (only `token_usage`, whose semantics — input vs. output vs. total —
are still an open question, agent-state.md §9 item 6), and no LLM node exists before Phase 2. Adding
a check against an undefined counter would be inventing a rule the plan has not made yet; Phase 2
(`feat/03-intent-extraction`) should add the counter it needs and extend `check_stop_conditions`
alongside it, not guess here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.graph.state import AgentState, RunStatus
from app.settings import Settings

#: A node's return value: a partial update to top-level `AgentState` fields (e.g. `"input"`,
#: `"observations"`), plus an optional `"control_patch"` key holding a partial update to
#: `ControlSection` (e.g. `{"status": RunStatus.NEEDS_INPUT}`). Nodes never construct
#: `ControlSection` themselves and never touch `step_count` — `guard_node` owns both, so a node
#: cannot accidentally skip the increment or race it.
NodeUpdate = dict[str, object]


class NodeFn(Protocol):
    """A node function's shape. A `Protocol` with a concrete `state: AgentState` parameter, not a
    `Callable[[AgentState], ...]` type alias: `StateGraph.add_node` infers its node-input type
    parameter from the callable it is given, and that inference only succeeds against a `Protocol`
    (mypy resolved it to `Never` through a `Callable` alias in testing — the alias's own generic
    machinery hides the concrete `AgentState` parameter type that inference needs)."""

    async def __call__(self, state: AgentState) -> NodeUpdate: ...


class GuardedNodeFn(Protocol):
    async def __call__(self, state: AgentState) -> dict[str, object]: ...


#: agent-state.md §9 item 1: the contract (00_API_AND_DATA_CONTRACTS.md §1) has no error code for a
#: budget ceiling, only for a dependency timeout. Proposed to module 02; not yet agreed.
BUDGET_EXCEEDED_ERROR_CODE = "AGENT_BUDGET_EXCEEDED"
_DEADLINE_ERROR_CODE = "DEPENDENCY_TIMEOUT"
_NOT_IMPLEMENTED_ERROR_CODE = "INTERNAL_ERROR"


class NodeNotImplementedError(RuntimeError):
    """Raised by a node whose tool integration has not shipped yet.

    Caught by `guard_node` and turned into a `FAILED` run with a stable, contract-approved error
    code — never left to crash the graph, and never allowed to fall through to a fabricated
    result. See the raising node's own module docstring for which phase/PR adds the real
    implementation.
    """


@dataclass(frozen=True, slots=True)
class StopCondition:
    status: RunStatus
    error_code: str | None = None


def check_stop_conditions(state: AgentState, settings: Settings) -> StopCondition | None:
    """Return the terminal condition a run must stop at, or `None` if it may proceed."""
    control = state.control
    if control.cancelled:
        return StopCondition(RunStatus.CANCELLED)
    if datetime.now(UTC) >= control.deadline_at:
        return StopCondition(RunStatus.FAILED, _DEADLINE_ERROR_CODE)
    over_budget = (
        control.step_count >= settings.max_agent_steps
        or control.tool_call_count >= settings.max_tool_calls
        or (
            settings.max_estimated_cost_usd is not None
            and control.estimated_cost >= settings.max_estimated_cost_usd
        )
    )
    if over_budget:
        return StopCondition(RunStatus.FAILED, BUDGET_EXCEEDED_ERROR_CODE)
    return None


def guard_node(name: str, fn: NodeFn, settings: Settings) -> GuardedNodeFn:
    """Wrap a node function with the step increment, the stop-condition check, and a safety net
    for `NodeNotImplementedError` — so every node in the graph gets identical, centrally-owned
    budget enforcement instead of re-implementing it.

    `name` is accepted (and set on the wrapper for readable stack traces / LangGraph node naming)
    even though it is not otherwise used yet: once observability lands (Phase 6) this is the one
    place a per-node span/metric can be attached without touching every node module.
    """

    async def wrapped(state: AgentState) -> dict[str, object]:
        incremented = state.control.model_copy(update={"step_count": state.control.step_count + 1})
        probe_state = state.model_copy(update={"control": incremented})

        stop = check_stop_conditions(probe_state, settings)
        if stop is not None:
            patch: dict[str, object] = {"status": stop.status}
            if stop.error_code is not None:
                patch["errors"] = [*incremented.errors, stop.error_code]
            return {"control": incremented.model_copy(update=patch)}

        try:
            result = await fn(probe_state)
        except NodeNotImplementedError:
            return {
                "control": incremented.model_copy(
                    update={
                        "status": RunStatus.FAILED,
                        "errors": [*incremented.errors, _NOT_IMPLEMENTED_ERROR_CODE],
                    }
                )
            }

        update = dict(result)
        control_patch_raw = update.pop("control_patch", None)
        control_patch = control_patch_raw if isinstance(control_patch_raw, dict) else None
        update["control"] = (
            incremented.model_copy(update=control_patch) if control_patch else incremented
        )
        return update

    wrapped.__name__ = name
    return wrapped
