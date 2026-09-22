from __future__ import annotations

import re

from app.domain.models import DecisionResult
from app.llm.schemas import ExplanationOutput

BANNED_PHRASES = ("guaranteed safe", "100% safe", "รับประกันความปลอดภัย", "ปลอดภัยแน่นอน")


class ExplanationValidationError(ValueError):
    pass


def validate_explanation(output: ExplanationOutput, locked: DecisionResult) -> ExplanationOutput:
    if output.action_code != locked.action_code:
        raise ExplanationValidationError("action_code differs from deterministic lock")
    allowed_codes = {reason.code for reason in locked.reasons}
    output_codes = {reason.code for reason in output.reasons}
    if not allowed_codes.issubset(output_codes):
        raise ExplanationValidationError("explanation omitted a locked reason code")
    if any(reason.code not in allowed_codes for reason in output.reasons):
        raise ExplanationValidationError("explanation contains an unapproved reason code")
    allowed_citations = {str(citation.get("source_id")) for citation in locked.citations}
    if any(citation not in allowed_citations for citation in output.citation_ids):
        raise ExplanationValidationError("explanation contains an unapproved citation")
    text = " ".join(
        [output.summary, *(reason.text for reason in output.reasons), *output.immediate_actions]
    )
    if any(phrase in text.lower() for phrase in BANNED_PHRASES):
        raise ExplanationValidationError("explanation contains a banned safety claim")
    if re.search(r"https?://|\b\d{3,}\b", text):
        raise ExplanationValidationError("explanation introduced an unverified URL or number")
    return output
