"""Checkpoint (de)serialization policy.

Registers exactly the one application type the checkpointer stores — `AgentState` — with
LangGraph's msgpack extension allowlist, instead of leaving it open to any Python type. This
matches this service's fail-closed default (`app/settings.py`, "Fail closed"): the checkpoint store
should not silently deserialize an arbitrary object it was never told to expect, even though the
running LangGraph version does not yet enforce that by default
(the `LANGGRAPH_STRICT_MSGPACK` environment variable is LangGraph's own opt-in for that).
"""

from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def agent_checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=[("app.graph.state", "AgentState")])
