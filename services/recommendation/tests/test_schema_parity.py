from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, RefResolver

from app.builders.recommendation_builder import RecommendationBuilder


@pytest.mark.asyncio
async def test_recommendation_matches_json_schema() -> None:
    # 1. Build a recommendation using standard fixtures
    builder = RecommendationBuilder()
    decision = {
        "decision_id": "00000000-0000-0000-0000-000000000001",
        "action_code": "NORMAL",
        "risk_level": "LOW",
        "confidence": 0.95,
        "explanation": "Conditions are calm and safe for travel.",
        "primary_action": "Continue normal journey.",
        "reasons": [
            {"code": "SPARSE_DATA_COVERAGE", "text": "Clear conditions with standard coverage"}
        ],
        "limitations": [],
        "validation": {"locked_action": True},
        "versions": {
            "policy_rule_set": "1.0.0",
            "scoring_model": "1.0.0",
            "prompt_template": "1.0.0",
        },
    }
    context = {
        "trip_id": "00000000-0000-0000-0000-000000000002",
        "request_id": "00000000-0000-0000-0000-000000000003",
        "country_code": "TH",
        "sources": [],
    }

    rec = await builder.build_recommendation(
        request_id="00000000-0000-0000-0000-000000000003",
        trip_id="00000000-0000-0000-0000-000000000002",
        decision=decision,
        context=context,
        locale="th-TH",
    )

    rec_dict = rec.model_dump(mode="json")

    # 2. Load the JSON schema
    root_dir = Path(__file__).parent.parent.parent.parent
    schema_dir = root_dir / "packages" / "contracts" / "jsonschema" / "common"
    main_schema_file = schema_dir / "recommendation-response.schema.json"

    if not main_schema_file.exists():
        pytest.skip(f"Schema file not found at {main_schema_file}")

    schema_text = main_schema_file.read_text(encoding="utf-8")
    main_schema = json.loads(schema_text)

    # Use RefResolver pointing to schema_dir
    resolver = RefResolver(
        base_uri=f"{schema_dir.resolve().as_uri()}/",
        referrer=main_schema,
    )

    validator = Draft202012Validator(main_schema, resolver=resolver)
    errors = list(validator.iter_errors(rec_dict))

    assert not errors, f"JSON Schema validation errors: {[e.message for e in errors]}"
