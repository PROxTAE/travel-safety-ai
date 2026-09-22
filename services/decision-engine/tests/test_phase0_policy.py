import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from app.policy.loader import load_policy

SERVICE_ROOT = Path(__file__).parents[1]


def test_policy_matches_schema_and_approval_checksum() -> None:
    policy_path = SERVICE_ROOT / "policies/v1/decision-table.yaml"
    document = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (SERVICE_ROOT / "schemas/decision-policy.schema.json").read_text(encoding="utf-8")
    )
    errors = list(Draft202012Validator(schema).iter_errors(document))
    assert errors == []
    checksum = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    registry = yaml.safe_load((SERVICE_ROOT / "policies/registry.yaml").read_text(encoding="utf-8"))
    approval = yaml.safe_load(
        (SERVICE_ROOT / "policies/v1/approval-record.yaml").read_text(encoding="utf-8")
    )
    assert registry["active"]["checksum_sha256"] == checksum
    assert approval["policy_checksum_sha256"] == checksum


def test_policy_priorities_are_unique_and_ascending() -> None:
    policy, _ = load_policy(SERVICE_ROOT / "policies/v1/decision-table.yaml")
    priorities = [rule["priority"] for rule in policy.rules]
    assert priorities == sorted(set(priorities))
    assert [rule["action"] for rule in policy.rules] == [
        "AVOID",
        "AVOID",
        "CHANGE_ROUTE",
        "DELAY",
        "NORMAL",
    ]


def test_policy_rule_trace_is_loaded_from_versioned_policy() -> None:
    policy, _ = load_policy(SERVICE_ROOT / "policies/v1/decision-table.yaml")
    assert [rule["id"] for rule in policy.rules] == [
        "R001_OFFICIAL_CLOSURE",
        "R002_HIGH_RISK_NO_SAFE_ROUTE",
        "R003_MATERIALLY_SAFER_ROUTE",
        "R004_TIME_DEPENDENT_RISK",
        "R005_LOW_RISK_USABLE_EVIDENCE",
    ]


def test_phase0_truth_table_has_all_actions_and_conservative_case() -> None:
    fixture = json.loads(
        (SERVICE_ROOT / "tests/golden/phase0_truth_table.json").read_text(encoding="utf-8")
    )
    actions = {case["expected_action"] for case in fixture["cases"]}
    assert actions == {"NORMAL", "CHANGE_ROUTE", "DELAY", "AVOID"}
    assert any(case.get("escalation_required") for case in fixture["cases"])
