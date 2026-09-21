from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from app.contracts import (
    CapabilityState,
    IntegratedTravelContext,
    RiskAssessData,
    RiskAssessResponse,
    StandardMeta,
)
from app.risk.fallback import assess_with_conservative_fallback

REPOSITORY_ROOT = (
    Path(configured_root)
    if (configured_root := os.environ.get("REPOSITORY_ROOT"))
    else Path(__file__).resolve().parents[4]
)
CONTRACT_SCHEMA = (
    REPOSITORY_ROOT
    / "packages"
    / "contracts"
    / "jsonschema"
    / "risk-knowledge"
    / "risk-knowledge-contract.schema.json"
)
ROUTE_ID = UUID("20000000-0000-4000-8000-000000000001")


def test_fallback_producer_response_matches_contract(
    snapshot: IntegratedTravelContext,
) -> None:
    response = RiskAssessResponse(
        data=RiskAssessData(
            assessments=assess_with_conservative_fallback(snapshot, [ROUTE_ID]),
            capability=CapabilityState(
                capability="RISK_MODEL",
                status="DEGRADED",
                version="fallback-safety-1.0.0",
                reason="NO_APPROVED_ACTIVE_MODEL",
            ),
            limitations=["MODEL_UNAVAILABLE"],
        ),
        meta=StandardMeta(
            request_id=UUID("50000000-0000-4000-8000-000000000001"),
            correlation_id=UUID("50000000-0000-4000-8000-000000000002"),
            generated_at=datetime.now(UTC),
            degraded_services=["risk-model"],
        ),
    )
    schema = json.loads(CONTRACT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": "#/$defs/RiskAssessResponse",
        },
        format_checker=FormatChecker(),
    ).validate(response.model_dump(mode="json"))
