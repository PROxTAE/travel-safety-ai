from __future__ import annotations

from app.domain.models import DecisionResult
from app.llm.client import LLMExplanationError, OpenAIExplainer
from app.llm.evidence import build_evidence_package
from app.llm.fallback import fallback_result
from app.llm.validators import ExplanationValidationError, validate_explanation
from app.settings import Settings


async def explain_result(result: DecisionResult, locale: str, settings: Settings) -> DecisionResult:
    if not settings.openai_enabled or settings.openai_api_key is None:
        return fallback_result(result, "LLM_DISABLED", locale)
    client = OpenAIExplainer(
        settings.openai_api_key.get_secret_value(),
        settings.openai_explainer_model,
        settings.openai_timeout_seconds,
        settings.openai_max_output_tokens,
    )
    for _attempt in range(2):
        try:
            output = await client.explain(build_evidence_package(result), locale)
            validated = validate_explanation(output, result)
            return result.model_copy(
                update={
                    "summary": validated.summary,
                    "reasons": [
                        reason.model_copy(
                            update={
                                "text": next(
                                    (
                                        item.text
                                        for item in validated.reasons
                                        if item.code == reason.code
                                    ),
                                    reason.text,
                                )
                            }
                        )
                        for reason in result.reasons
                    ],
                    "versions": {
                        **result.versions,
                        "llm_model": settings.openai_explainer_model,
                        "prompt": "1.0.0",
                    },
                }
            )
        except (LLMExplanationError, ExplanationValidationError):
            continue
    return fallback_result(result, "LLM_VALIDATION_OR_PROVIDER_FAILURE", locale)
