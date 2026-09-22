from __future__ import annotations

from typing import Any

from app.domain.models import DecisionResult


def build_evidence_package(result: DecisionResult) -> dict[str, Any]:
    """Expose only locked decision facts to the explanation model."""
    return {
        "locked_action": result.action_code.value,
        "risk_level": result.risk_level.value,
        "confidence": result.confidence,
        "rules_fired": list(result.rules_fired),
        "reasons": [
            {"code": reason.code, "source_ids": list(reason.source_ids)}
            for reason in result.reasons
        ],
        "citation_ids": [str(citation.get("source_id")) for citation in result.citations],
        "limitations": [limitation.get("code") for limitation in result.limitations],
    }
