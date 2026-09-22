"""`integrate_data` node.

Not implemented until Phase 3/4 add the typed `data_integration.create_snapshot@1` client. Needs
`observations.external_context_ref` from `fetch_external_data`, which does not exist yet either.
"""

from __future__ import annotations

from app.graph.nodes._stub import not_implemented_node

integrate_data = not_implemented_node(
    "integrate_data", "data_integration.create_snapshot@1 is not wired yet (Phase 3/4)"
)
