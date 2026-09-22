"""Factory for nodes whose tool integration has not shipped yet.

Every node built here raises `NodeNotImplementedError` unconditionally instead of returning a
fabricated result. `guard_node` (app/budgets) catches it and ends the run `FAILED` with the stable
`INTERNAL_ERROR` contract code — the plan is explicit that this scaffold must never expose a
demo/fake recommendation (03_TRAVEL_AI_AGENT_IMPLEMENTATION.md, Phase 1 exit criterion).

Not exported outside `app.graph.nodes`: each node module below wraps one call to this with its own
docstring naming the specific tool and phase that replaces it, so `docs/diagrams/agent-state.md`'s
node table stays traceable to one file per node.
"""

from __future__ import annotations

from app.budgets import NodeFn, NodeNotImplementedError
from app.graph.state import AgentState


def not_implemented_node(node_name: str, reason: str) -> NodeFn:
    async def node(state: AgentState) -> dict[str, object]:
        del state  # unused: the node fails before it would ever read state
        raise NodeNotImplementedError(f"{node_name}: {reason}")

    node.__name__ = node_name
    return node
