"""`build_evidence` node.

Not implemented until Phase 3/4 add the typed `risk_knowledge.build_evidence_package@1` client.
Needs `observations.snapshot_id` from `integrate_data`, which does not exist yet either.
"""

from __future__ import annotations

from app.graph.nodes._stub import not_implemented_node

build_evidence = not_implemented_node(
    "build_evidence", "risk_knowledge.build_evidence_package@1 is not wired yet (Phase 3/4)"
)
