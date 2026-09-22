"""Per-`Intent` critical-field matrix — `docs/intent-and-required-fields.md` §2.

The one rule Phase 1's `check_required_fields` already enforces for every intent
(`confirmed_by_user` on both locations, 00_API_AND_DATA_CONTRACTS.md §3.1) stays in
`app/graph/nodes/check_required_fields.py` itself — this module only adds the per-`Intent` extras
the table in the doc lists.
"""

from __future__ import annotations

from app.graph.state import InputSection, Intent


def missing_fields_for_intent(intent: Intent, input_section: InputSection) -> list[str]:
    if intent is Intent.FOLLOW_UP and input_section.travel_request.conversation_id is None:
        # A FOLLOW_UP with no conversation to follow up on is a classifier inconsistency, not a
        # silent bug: surface it the same way a genuinely missing field is surfaced.
        return ["conversation_id"]
    return []
