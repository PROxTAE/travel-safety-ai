from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field


class PolicyThresholds(BaseModel):
    high_risk_score: float = Field(ge=0, le=1)
    materially_safer_delta: float = Field(gt=0, le=1)
    alternative_min_quality: float = Field(ge=0, le=1)
    delay_risk_score: float = Field(ge=0, le=1)
    max_delay_minutes: int = Field(gt=0)
    minimum_confidence: float = Field(ge=0, le=1)
    threshold_margin: float = Field(default=0.05, ge=0, le=1)
    max_uncertainty: float = Field(default=0.25, ge=0, le=1)


class Policy(BaseModel):
    version: str
    contract_version: str
    status: str
    thresholds: PolicyThresholds
    rules: list[dict[str, Any]]


def load_policy(path: Path, expected_checksum: str | None = None) -> tuple[Policy, str]:
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if expected_checksum and checksum != expected_checksum:
        raise ValueError("decision policy checksum does not match configured checksum")
    document = yaml.safe_load(raw)
    schema_path = path.parents[2] / "schemas" / "decision-policy.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path)
    )
    if errors:
        raise ValueError(f"decision policy schema validation failed: {errors[0].message}")
    policy = Policy.model_validate(document)
    if policy.status != "APPROVED":
        raise ValueError("decision policy is not approved")
    return policy, checksum
