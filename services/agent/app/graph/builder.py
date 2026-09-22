"""LangGraph `StateGraph` builder for the agent (module 03).

Wires the full node/edge shape from docs/diagrams/agent-state.md §2. Seven of the thirteen nodes
still raise `NodeNotImplementedError` — `fetch_external_data`, `integrate_data`, `build_evidence`,
`degraded_or_escalate`, `make_decision`, `format_recommendation`, `emergency_shortcut` — because
they need a Module 04/07/08 contract that has not been published yet (see each node module's own
docstring). `validate_evidence`'s retry-vs-escalate branch is real as of Phase 4, even though
nothing can drive it end-to-end until `build_evidence` is unblocked.

`GRAPH_VERSION` and `graph_checksum()` are what `AgentState.versions.graph` records on every run,
so a checkpoint stays attributable to the exact graph shape that produced it even after this file
changes later.
"""

from __future__ import annotations

import hashlib

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.budgets import GuardedNodeFn, NodeFn, guard_node
from app.graph import routing
from app.graph.nodes.build_evidence import build_evidence
from app.graph.nodes.check_required_fields import check_required_fields
from app.graph.nodes.classify_intent import build_classify_intent_node
from app.graph.nodes.degraded_or_escalate import degraded_or_escalate
from app.graph.nodes.emergency_shortcut import emergency_shortcut
from app.graph.nodes.fetch_external_data import fetch_external_data
from app.graph.nodes.finalize import finalize
from app.graph.nodes.format_recommendation import format_recommendation
from app.graph.nodes.integrate_data import integrate_data
from app.graph.nodes.make_decision import make_decision
from app.graph.nodes.validate_evidence import validate_evidence
from app.graph.nodes.validate_final_contract import validate_final_contract
from app.graph.nodes.validate_input import validate_input
from app.graph.state import AgentState
from app.intent.llm_classifier import build_llm_classifier
from app.settings import Settings

#: Bumped whenever a node, edge or routing rule changes shape. Independent of the package/service
#: version in `app/__init__.py`: this tracks the *graph*, not the deployable artifact.
GRAPH_VERSION = "0.3.0"

#: Node names in the order they are registered — the input to `graph_checksum()`. Keeping this as
#: an explicit tuple (rather than deriving it from the compiled graph) means the checksum changes
#: the moment this list is edited, without needing a compiled graph on hand to compute it.
_NODE_ORDER = (
    "validate_input",
    "classify_intent",
    "emergency_shortcut",
    "check_required_fields",
    "fetch_external_data",
    "integrate_data",
    "build_evidence",
    "validate_evidence",
    "degraded_or_escalate",
    "make_decision",
    "format_recommendation",
    "validate_final_contract",
    "finalize",
)


def graph_checksum() -> str:
    """Deterministic fingerprint of the compiled shape.

    Two processes running the same code always compute the same value; changing a node's position
    in `_NODE_ORDER`, adding a node, or bumping `GRAPH_VERSION` changes it.
    """
    payload = "|".join((GRAPH_VERSION, *_NODE_ORDER))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def build_graph(
    settings: Settings,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)
    llm_classifier = build_llm_classifier(settings)

    def add(name: str, fn: NodeFn) -> None:
        guarded: GuardedNodeFn = guard_node(name, fn, settings)
        graph.add_node(name, guarded)

    add("validate_input", validate_input)
    add("classify_intent", build_classify_intent_node(settings, llm_classifier))
    add("emergency_shortcut", emergency_shortcut)
    add("check_required_fields", check_required_fields)
    add("fetch_external_data", fetch_external_data)
    add("integrate_data", integrate_data)
    add("build_evidence", build_evidence)
    add("validate_evidence", validate_evidence)
    add("degraded_or_escalate", degraded_or_escalate)
    add("make_decision", make_decision)
    add("format_recommendation", format_recommendation)
    add("validate_final_contract", validate_final_contract)
    add("finalize", finalize)

    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges(
        "validate_input", routing.after_guarded, {"stopped": END, "continue": "classify_intent"}
    )
    graph.add_conditional_edges(
        "classify_intent",
        routing.after_classify_intent,
        {
            "stopped": END,
            "emergency": "emergency_shortcut",
            "continue": "check_required_fields",
        },
    )
    # A successful emergency_shortcut goes straight to finalize — it deliberately bypasses
    # validate_final_contract (which requires a recommendation_id) since the emergency path never
    # produces one; only the normal recommendation pipeline does.
    graph.add_conditional_edges(
        "emergency_shortcut", routing.after_guarded, {"stopped": END, "continue": "finalize"}
    )
    graph.add_conditional_edges(
        "check_required_fields",
        routing.after_check_required_fields,
        {"stopped": END, "needs_input": END, "continue": "fetch_external_data"},
    )
    graph.add_conditional_edges(
        "fetch_external_data",
        routing.after_guarded,
        {"stopped": END, "continue": "integrate_data"},
    )
    graph.add_conditional_edges(
        "integrate_data", routing.after_guarded, {"stopped": END, "continue": "build_evidence"}
    )
    graph.add_conditional_edges(
        "build_evidence", routing.after_guarded, {"stopped": END, "continue": "validate_evidence"}
    )
    # The graph's one back-edge, bounded by evidence_retry_count vs. evidence_retry_max — see
    # app/graph/nodes/validate_evidence.py and app/graph/routing.build_after_validate_evidence.
    graph.add_conditional_edges(
        "validate_evidence",
        routing.build_after_validate_evidence(settings),
        {
            "stopped": END,
            "retry": "build_evidence",
            "escalate": "degraded_or_escalate",
            "continue": "make_decision",
        },
    )
    graph.add_conditional_edges(
        "degraded_or_escalate",
        routing.after_guarded,
        {"stopped": END, "continue": "make_decision"},
    )
    graph.add_conditional_edges(
        "make_decision",
        routing.after_guarded,
        {"stopped": END, "continue": "format_recommendation"},
    )
    graph.add_conditional_edges(
        "format_recommendation",
        routing.after_guarded,
        {"stopped": END, "continue": "validate_final_contract"},
    )
    graph.add_conditional_edges(
        "validate_final_contract",
        routing.after_validate_final_contract,
        {"invalid": END, "valid": "finalize"},
    )
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer, name=f"agent-graph-{GRAPH_VERSION}")
