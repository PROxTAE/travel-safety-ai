import hashlib
from pathlib import Path

import pytest
import yaml
from test_evaluator import POLICY, make_request

from app.domain.models import ActionCode
from app.llm.evidence import build_evidence_package
from app.llm.schemas import ExplanationOutput
from app.llm.validators import ExplanationValidationError, validate_explanation
from app.policy.evaluator import build_result, evaluate
from app.policy.rollback import RollbackError, verified_rollback_target

SERVICE_ROOT = Path(__file__).parents[1]


def test_official_closure_cannot_be_lowered_by_low_model_score() -> None:
    payload = make_request(
        0.05, official_alerts=[{"source_id": "official-closure", "closure": True}]
    )
    result = build_result(payload, POLICY, evaluate(payload, POLICY))
    assert result.action_code == ActionCode.AVOID
    assert result.rules_fired == ["R001_OFFICIAL_CLOSURE"]


def test_untrusted_instruction_is_not_sent_as_explanation_evidence() -> None:
    payload = make_request(0.1)
    result = build_result(payload, POLICY, evaluate(payload, POLICY))
    package = build_evidence_package(result)
    package_text = str(package).lower()
    assert "ignore previous instructions" not in package_text
    assert set(package) == {
        "locked_action",
        "risk_level",
        "confidence",
        "rules_fired",
        "reasons",
        "citation_ids",
        "limitations",
    }


def test_validator_rejects_hallucinated_action_citation_and_number() -> None:
    locked = build_result(make_request(0.1), POLICY, evaluate(make_request(0.1), POLICY))
    attacks = [
        ExplanationOutput(
            action_code=ActionCode.AVOID,
            summary="x",
            reasons=[{"code": "NO_ACTIVE_RESTRICTION", "text": "x"}],
            immediate_actions=[],
            limitations=[],
            citation_ids=[],
        ),
        ExplanationOutput(
            action_code=ActionCode.NORMAL,
            summary="x",
            reasons=[{"code": "NO_ACTIVE_RESTRICTION", "text": "x"}],
            immediate_actions=[],
            limitations=[],
            citation_ids=["forged"],
        ),
        ExplanationOutput(
            action_code=ActionCode.NORMAL,
            summary="Call 999 now",
            reasons=[{"code": "NO_ACTIVE_RESTRICTION", "text": "x"}],
            immediate_actions=[],
            limitations=[],
            citation_ids=[],
        ),
    ]
    for attack in attacks:
        with pytest.raises(ExplanationValidationError):
            validate_explanation(attack, locked)


def test_unsupported_locale_falls_back_without_claiming_support() -> None:
    result = build_result(
        make_request(0.1, locale="xx-UNSUPPORTED"),
        POLICY,
        evaluate(make_request(0.1, locale="xx-UNSUPPORTED"), POLICY),
    )
    assert result.summary
    assert result.action_code == ActionCode.NORMAL


def test_rollback_drill_verifies_previous_checksum_and_approval(tmp_path: Path) -> None:
    previous = tmp_path / "previous.yaml"
    previous.write_text("version: 0.9.0\nstatus: APPROVED\n", encoding="utf-8")
    checksum = hashlib.sha256(previous.read_bytes()).hexdigest()
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "rollback": {
                    "previous": {
                        "path": "previous.yaml",
                        "checksum_sha256": checksum,
                        "status": "APPROVED",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    target, actual = verified_rollback_target(registry)
    assert target == previous
    assert actual == checksum


def test_rollback_drill_rejects_tampered_previous_policy(tmp_path: Path) -> None:
    previous = tmp_path / "previous.yaml"
    previous.write_text("version: 0.9.0\nstatus: APPROVED\n", encoding="utf-8")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "rollback": {
                    "previous": {
                        "path": "previous.yaml",
                        "checksum_sha256": "0" * 64,
                        "status": "APPROVED",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RollbackError, match="checksum"):
        verified_rollback_target(registry)
