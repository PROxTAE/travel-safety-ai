"""`degraded_or_escalate` node.

Not implemented yet: the branch between "policy allows a conservative result" and "policy requires
human review" (agent-state.md §2) is Module 07's decision policy, and agent-state.md §9 item 2
records that even the *status* an escalation ends in is still an open question with Module 07.
Phase 5 (`feat/03-followup-degraded`) owns this node.
"""

from __future__ import annotations

from app.graph.nodes._stub import not_implemented_node

degraded_or_escalate = not_implemented_node(
    "degraded_or_escalate", "escalation policy is owned by module 07 and not agreed yet (Phase 5)"
)
