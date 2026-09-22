"""`make_decision` node.

Not implemented until Phase 3/4 add the typed `decision_engine.create_decision@1` client. The
agent never decides risk or action itself — this node's only job, once implemented, is to send the
validated evidence package to Module 07 and record `result.decision_id` from its locked response.
"""

from __future__ import annotations

from app.graph.nodes._stub import not_implemented_node

make_decision = not_implemented_node(
    "make_decision", "decision_engine.create_decision@1 is not wired yet (Phase 3/4)"
)
