import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_evaluator import POLICY, make_request

from app.domain.models import ActionCode, DecisionResult
from app.llm.client import LLMExplanationError, OpenAIExplainer
from app.llm.evidence import build_evidence_package
from app.llm.prompts import render_explanation_prompt
from app.llm.schemas import ExplanationOutput
from app.llm.service import explain_result
from app.llm.validators import ExplanationValidationError, validate_explanation
from app.policy.evaluator import build_result, evaluate
from app.settings import Settings

SERVICE_ROOT = Path(__file__).parents[1]


def locked_result(locale: str = "en-US") -> DecisionResult:
    payload = make_request(0.1, locale=locale)
    return build_result(payload, POLICY, evaluate(payload, POLICY))


def test_explanation_schema_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ExplanationOutput.model_validate(
            {
                "action_code": "NORMAL",
                "summary": "ok",
                "reasons": [],
                "immediate_actions": [],
                "limitations": [],
                "citation_ids": [],
                "action_override": "AVOID",
            }
        )


def test_prompt_contains_only_package_and_strict_schema_instructions() -> None:
    prompt = render_explanation_prompt(build_evidence_package(locked_result()), "en-US")
    assert "Never change action_code" in prompt
    assert '"additionalProperties": false' in prompt
    assert "chain-of-thought" not in prompt


def test_validator_rejects_action_change_and_unknown_citation() -> None:
    locked = locked_result()
    changed = ExplanationOutput(
        action_code=ActionCode.AVOID,
        summary="No",
        reasons=[],
        immediate_actions=[],
        limitations=[],
        citation_ids=[],
    )
    with pytest.raises(ExplanationValidationError, match="action_code"):
        validate_explanation(changed, locked)
    unknown_citation = ExplanationOutput(
        action_code=ActionCode.NORMAL,
        summary="Ok",
        reasons=[
            {"code": "NO_ACTIVE_RESTRICTION", "text": "No higher-priority safety rule applies."}
        ],
        immediate_actions=[],
        limitations=[],
        citation_ids=["unapproved"],
    )
    with pytest.raises(ExplanationValidationError, match="citation"):
        validate_explanation(unknown_citation, locked)


def test_validator_rejects_omitted_locked_reason() -> None:
    locked = locked_result()
    output = ExplanationOutput(
        action_code=ActionCode.NORMAL,
        summary="Ok",
        reasons=[],
        immediate_actions=[],
        limitations=[],
        citation_ids=[],
    )
    with pytest.raises(ExplanationValidationError, match="omitted"):
        validate_explanation(output, locked)


def test_validator_rejects_banned_claim_and_unverified_number() -> None:
    locked = locked_result()
    banned = ExplanationOutput(
        action_code=ActionCode.NORMAL,
        summary="This is 100% safe",
        reasons=[],
        immediate_actions=[],
        limitations=[],
        citation_ids=[],
    )
    with pytest.raises(ExplanationValidationError):
        validate_explanation(banned, locked)
    number = ExplanationOutput(
        action_code=ActionCode.NORMAL,
        summary="Call 191 now",
        reasons=[],
        immediate_actions=[],
        limitations=[],
        citation_ids=[],
    )
    with pytest.raises(ExplanationValidationError):
        validate_explanation(number, locked)


def test_disabled_llm_returns_localized_fallback_without_network() -> None:
    english = asyncio.run(explain_result(locked_result(), "en-US", Settings(openai_enabled=False)))
    thai = asyncio.run(
        explain_result(locked_result("th-TH"), "th-TH", Settings(openai_enabled=False))
    )
    assert english.versions["llm_model"] is None
    assert english.limitations[-1]["code"] == "EXPLANATION_FALLBACK_TEMPLATE"
    assert thai.summary.startswith("หลักฐาน")


def test_openai_client_maps_refusal_and_incomplete() -> None:
    async def refusal(**_: object) -> object:
        return SimpleNamespace(
            status="completed", output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])]
        )

    refusal_client = SimpleNamespace(responses=SimpleNamespace(create=refusal))
    client = OpenAIExplainer("test-key", "test-model", 1, 100, refusal_client)
    with pytest.raises(LLMExplanationError, match="refused"):
        asyncio.run(client.explain(build_evidence_package(locked_result()), "en-US"))

    async def incomplete(**_: object) -> object:
        return SimpleNamespace(status="incomplete", output=[])

    incomplete_client = SimpleNamespace(responses=SimpleNamespace(create=incomplete))
    client = OpenAIExplainer("test-key", "test-model", 1, 100, incomplete_client)
    with pytest.raises(LLMExplanationError, match="incomplete"):
        asyncio.run(client.explain(build_evidence_package(locked_result()), "en-US"))


def test_openai_client_sends_strict_no_store_request() -> None:
    calls: list[dict[str, object]] = []

    async def complete(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(
            status="completed",
            output_text=(
                '{"action_code":"NORMAL","summary":"Validated route evidence supports the plan.",'
                '"reasons":[{"code":"NO_ACTIVE_RESTRICTION",'
                '"text":"No higher-priority safety rule applies."}],'
                '"immediate_actions":[],"limitations":[],"citation_ids":[]}'
            ),
            output=[],
        )

    client = OpenAIExplainer(
        "test-key",
        "test-model",
        1,
        100,
        SimpleNamespace(responses=SimpleNamespace(create=complete)),
    )
    output = asyncio.run(client.explain(build_evidence_package(locked_result()), "en-US"))
    assert output.action_code == ActionCode.NORMAL
    assert calls[0]["store"] is False
    assert calls[0]["text"]["format"]["strict"] is True
