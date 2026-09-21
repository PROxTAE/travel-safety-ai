from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import OpenAPIV31SpecValidator

REPOSITORY_ROOT = (
    Path(configured_root)
    if (configured_root := os.environ.get("REPOSITORY_ROOT"))
    else Path(__file__).resolve().parents[4]
)
SERVICE_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SCHEMA = (
    REPOSITORY_ROOT
    / "packages"
    / "contracts"
    / "jsonschema"
    / "risk-knowledge"
    / "risk-knowledge-contract.schema.json"
)
OPENAPI = REPOSITORY_ROOT / "packages" / "contracts" / "openapi" / "internal-risk-knowledge.yaml"


def test_json_schemas_are_valid_draft_2020_12() -> None:
    for path in (
        CONTRACT_SCHEMA,
        SERVICE_ROOT / "training" / "dataset_manifest.schema.json",
        SERVICE_ROOT / "knowledge" / "sources.schema.json",
    ):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_openapi_document_is_valid() -> None:
    specification = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    vocabulary = json.loads(CONTRACT_SCHEMA.read_text(encoding="utf-8"))
    bundled_definitions = {
        name: _rewrite_refs(deepcopy(value), external=False)
        for name, value in vocabulary["$defs"].items()
    }
    specification["components"]["schemas"].update(bundled_definitions)
    bundled = _rewrite_refs(specification, external=True)
    OpenAPIV31SpecValidator(bundled).validate()


def _rewrite_refs(value: Any, *, external: bool) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_refs(item, external=external) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_refs(item, external=external) for item in value]
    if isinstance(value, str) and value.startswith("#/$defs/"):
        return value.replace("#/$defs/", "#/components/schemas/", 1)
    external_prefix = "../jsonschema/risk-knowledge/risk-knowledge-contract.schema.json#/$defs/"
    if external and isinstance(value, str) and value.startswith(external_prefix):
        return value.replace(external_prefix, "#/components/schemas/", 1)
    return value


def test_empty_knowledge_manifest_is_explicitly_valid() -> None:
    schema = json.loads(
        (SERVICE_ROOT / "knowledge" / "sources.schema.json").read_text(encoding="utf-8")
    )
    manifest = yaml.safe_load(
        (SERVICE_ROOT / "knowledge" / "sources.yaml").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
    assert manifest["sources"] == []
    assert manifest["collection_version"] == "uninitialized"


def test_governance_configs_fail_closed_pending_approval() -> None:
    feature_schema = yaml.safe_load(
        (SERVICE_ROOT / "governance" / "feature_schema.v1.yaml").read_text(encoding="utf-8")
    )
    acceptance = yaml.safe_load(
        (SERVICE_ROOT / "governance" / "model_acceptance.yaml").read_text(encoding="utf-8")
    )
    route_policy = yaml.safe_load(
        (SERVICE_ROOT / "governance" / "route_exposure_policy.v1.yaml").read_text(encoding="utf-8")
    )
    assert feature_schema["status"].startswith("PROPOSED")
    assert acceptance["status"].startswith("PENDING")
    assert acceptance["thresholds"]["high_risk_recall_min"] is None
    assert acceptance["approval_guard"]["reject_null_safety_thresholds"] is True
    assert route_policy["status"].startswith("PENDING")
    assert route_policy["exposure_formula"]["coefficients"]["severity_weights"] is None
    assert route_policy["ranking"]["pending_numeric_coefficients_behavior"].startswith(
        "enforce_hard_constraints"
    )


def test_official_alert_feature_null_policy_matches_lead_decisions() -> None:
    feature_schema = yaml.safe_load(
        (SERVICE_ROOT / "governance" / "feature_schema.v1.yaml").read_text(encoding="utf-8")
    )
    features = {feature["name"]: feature for feature in feature_schema["features"]}

    assert feature_schema["null_policy"]["model_behavior"] == (
        "route_assessment_must_be_UNKNOWN_when_any_critical_feature_is_null"
    )
    assert features["corridor_official_closure_active"]["nullable"] is True
    assert features["corridor_official_closure_active"]["critical"] is True
    assert features["corridor_extreme_alert_active"]["nullable"] is True
    assert features["corridor_extreme_alert_active"]["critical"] is True
    assert features["corridor_official_evacuation_active"]["nullable"] is True
    assert features["corridor_official_evacuation_active"]["critical"] is False
