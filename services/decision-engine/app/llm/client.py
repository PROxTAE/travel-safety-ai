from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.llm.prompts import render_explanation_prompt
from app.llm.schemas import EXPLANATION_JSON_SCHEMA, ExplanationOutput


class LLMExplanationError(RuntimeError):
    """A safe explanation failure that triggers deterministic fallback."""


class OpenAIExplainer:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_output_tokens: int,
        client: Any | None = None,
    ) -> None:
        self._client = client or AsyncOpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def explain(self, package: dict[str, Any], locale: str) -> ExplanationOutput:
        try:
            response = await self._client.responses.create(
                model=self._model,
                input=[
                    {"role": "system", "content": "Format only validated travel-safety evidence."},
                    {"role": "user", "content": render_explanation_prompt(package, locale)},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "decision_explanation",
                        "strict": True,
                        "schema": EXPLANATION_JSON_SCHEMA,
                    }
                },
                store=False,
                temperature=0,
                max_output_tokens=self._max_output_tokens,
            )
        except Exception as exc:
            raise LLMExplanationError("LLM explanation request failed") from exc
        if getattr(response, "status", None) == "incomplete":
            raise LLMExplanationError("LLM explanation was incomplete")
        if _find_refusal(response):
            raise LLMExplanationError("LLM refused the explanation")
        raw = getattr(response, "output_text", None)
        if not raw:
            raise LLMExplanationError("LLM returned no explanation")
        try:
            return ExplanationOutput.model_validate(json.loads(raw))
        except (ValueError, TypeError) as exc:
            raise LLMExplanationError("LLM explanation was not valid JSON") from exc


def _find_refusal(response: Any) -> bool:
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                return True
    return False
