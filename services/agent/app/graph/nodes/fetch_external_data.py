"""`fetch_external_data` node.

Not implemented until Phase 3 (`feat/03-tool-registry`) adds the typed
`external_data.query_context@1` client and Phase 4 (`feat/03-orchestration-path`) wires it in here.
Raising instead of returning a fabricated `observations.external_context_ref` is deliberate: the
plan forbids this scaffold from ever exposing a demo/fake result.
"""

from __future__ import annotations

from app.graph.nodes._stub import not_implemented_node

fetch_external_data = not_implemented_node(
    "fetch_external_data", "external_data.query_context@1 is not wired yet (Phase 3/4)"
)
