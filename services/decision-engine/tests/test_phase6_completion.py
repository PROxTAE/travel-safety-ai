import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from test_evaluator import make_request

from app.domain.models import ActionCode
from app.llm.service import explain_result
from app.policy.evaluator import build_result, evaluate
from app.policy.loader import load_policy
from app.repositories.replay import AuditReplay, replay_audit_record
from app.settings import Settings

SERVICE_ROOT = Path(__file__).parents[1]
POLICY, POLICY_CHECKSUM = load_policy(SERVICE_ROOT / "policies/v1/decision-table.yaml")


def test_local_acceptance_covers_all_four_actions() -> None:
    cases = [
        (make_request(0.1), ActionCode.NORMAL),
        (make_request(0.8), ActionCode.AVOID),
        (make_request(0.8, 0.5), ActionCode.CHANGE_ROUTE),
        (
            make_request(
                0.5,
                assessments=[
                    {
                        "snapshot_id": "00000000-0000-0000-0000-000000000002",
                        "route_id": "00000000-0000-0000-0000-000000000003",
                        "score": 0.5,
                        "risk_level": "MEDIUM",
                        "reason_codes": ["LONG_EXPOSURE_WINDOW"],
                        "quality": {"status": "FRESH", "score": 0.95},
                    }
                ],
            ),
            ActionCode.DELAY,
        ),
    ]
    for payload, expected in cases:
        assert evaluate(payload, POLICY).action == expected


def test_fallback_acceptance_without_llm_is_locked_and_valid() -> None:
    payload = make_request(0.1, locale="th-TH")
    result = build_result(payload, POLICY, evaluate(payload, POLICY))
    fallback = asyncio.run(explain_result(result, payload.locale, Settings(openai_enabled=False)))
    assert fallback.action_code == result.action_code
    assert fallback.validation["locked_action"] is True
    assert fallback.limitations[-1]["code"] == "EXPLANATION_FALLBACK_TEMPLATE"


def test_audit_replay_excludes_sensitive_payload_and_preserves_trace() -> None:
    record = {
        "audit_id": uuid4(),
        "decision_id": uuid4(),
        "request_id": uuid4(),
        "snapshot_id": uuid4(),
        "action_code": "AVOID",
        "confidence": 0.9,
        "escalation_required": True,
        "policy_version": POLICY.version,
        "policy_checksum": POLICY_CHECKSUM,
        "rules_fired": ["R001_OFFICIAL_CLOSURE"],
        "input_hash": "a" * 64,
        "output_hash": "b" * 64,
    }
    replay = replay_audit_record(record)
    assert isinstance(replay, AuditReplay)
    assert not hasattr(replay, "summary")
    assert not hasattr(replay, "prompt")
    assert replay.action_code == "AVOID"


def test_audit_replay_rejects_unapproved_sensitive_fields() -> None:
    record = {
        "audit_id": uuid4(),
        "decision_id": uuid4(),
        "request_id": uuid4(),
        "snapshot_id": uuid4(),
        "action_code": "NORMAL",
        "confidence": 0.8,
        "escalation_required": False,
        "policy_version": POLICY.version,
        "policy_checksum": POLICY_CHECKSUM,
        "rules_fired": ["R005_LOW_RISK_USABLE_EVIDENCE"],
        "input_hash": "a" * 64,
        "output_hash": "b" * 64,
        "prompt": "secret",
    }
    with pytest.raises(ValueError):
        replay_audit_record(record)
