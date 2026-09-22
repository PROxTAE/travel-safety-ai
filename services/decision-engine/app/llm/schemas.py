from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import ActionCode


class ExplanationReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=1000)


class ExplanationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_code: ActionCode
    summary: str = Field(min_length=1, max_length=1000)
    reasons: list[ExplanationReason] = Field(max_length=5)
    immediate_actions: list[str] = Field(max_length=5)
    limitations: list[str] = Field(max_length=5)
    citation_ids: list[str] = Field(max_length=20)


EXPLANATION_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "action_code",
        "summary",
        "reasons",
        "immediate_actions",
        "limitations",
        "citation_ids",
    ],
    "properties": {
        "action_code": {"type": "string", "enum": [action.value for action in ActionCode]},
        "summary": {"type": "string", "minLength": 1, "maxLength": 1000},
        "reasons": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "text"],
                "properties": {
                    "code": {"type": "string", "maxLength": 128},
                    "text": {"type": "string", "maxLength": 1000},
                },
            },
        },
        "immediate_actions": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 512},
        },
        "limitations": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 512},
        },
        "citation_ids": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string", "maxLength": 128},
        },
    },
}
