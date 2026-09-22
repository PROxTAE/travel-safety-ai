from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
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
    policy = Policy.model_validate(yaml.safe_load(raw))
    if policy.status != "APPROVED":
        raise ValueError("decision policy is not approved")
    return policy, checksum