from __future__ import annotations

from app.domain.models import DecisionResult
from app.policy.fallback import localized_summary


def fallback_result(result: DecisionResult, reason: str, locale: str = "en-US") -> DecisionResult:
    limitations = [*result.limitations, {"code": "EXPLANATION_FALLBACK_TEMPLATE", "text": reason}]
    return result.model_copy(
        update={
            "summary": localized_summary(result.action_code, locale),
            "limitations": limitations,
            "versions": {**result.versions, "llm_model": None, "prompt": None},
            "validation": {**result.validation, "locked_action": True},
        }
    )
