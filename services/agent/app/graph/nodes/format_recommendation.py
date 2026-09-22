"""`format_recommendation` node.

Not implemented until Phase 3/4 add the typed `recommendation.create_recommendation@1` client.
Sends the locked `DecisionResult` to Module 08 and records `result.recommendation_id` — this node
never edits the decision it was given.
"""

from __future__ import annotations

from app.graph.nodes._stub import not_implemented_node

format_recommendation = not_implemented_node(
    "format_recommendation", "recommendation.create_recommendation@1 is not wired yet (Phase 3/4)"
)
