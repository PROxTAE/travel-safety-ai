"""`emergency_shortcut` node — Phase 2 graph-shape addition.

`03_TRAVEL_AI_AGENT_IMPLEMENTATION.md` Phase 0 step 3 is explicit: "emergency ต้องส่งทางลัดไปข้อมูล
ฉุกเฉินแต่ไม่ auto-contact" (an emergency intent takes a shortcut straight to emergency information,
never auto-contacts anyone). `app/graph/routing.after_classify_intent` sends `EMERGENCY` runs here
directly from `classify_intent` — skipping `check_required_fields`, `fetch_external_data`,
`integrate_data` and `build_evidence` entirely, which is the shortcut itself.

The actual "emergency information" is `GET /internal/v1/emergency/contacts` on Module 08
(recommendation) — 00_API_AND_DATA_CONTRACTS.md §5.6 — and it is not one of the plan's five
allowlisted MVP tools, and module 08 has not published an OpenAPI contract for it yet
(`packages/contracts/openapi/` has only `internal-data-integration.yaml` and
`internal-risk-knowledge.yaml`). Until it exists, this node raises `NodeNotImplementedError`
rather than returning fabricated emergency contact information — of every node in this graph,
this is the one place a fabricated result would be most dangerous.
"""

from __future__ import annotations

from app.graph.nodes._stub import not_implemented_node

emergency_shortcut = not_implemented_node(
    "emergency_shortcut",
    "recommendation's emergency/contacts endpoint has no published OpenAPI contract yet "
    "(owned by module 08, not one of the plan's 5 allowlisted MVP tools)",
)
