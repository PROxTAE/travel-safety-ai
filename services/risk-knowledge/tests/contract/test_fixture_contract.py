from __future__ import annotations

import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

REPOSITORY_ROOT = (
    Path(configured_root)
    if (configured_root := os.environ.get("REPOSITORY_ROOT"))
    else Path(__file__).resolve().parents[4]
)
SERVICE_ROOT = Path(__file__).resolve().parents[2]


def test_sanitized_real_provider_fixture_validates() -> None:
    schema_path = (
        REPOSITORY_ROOT
        / "packages"
        / "contracts"
        / "jsonschema"
        / "risk-knowledge"
        / "risk-knowledge-contract.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    fixture = json.loads(
        (SERVICE_ROOT / "tests" / "fixtures" / "usgs_route_context.json").read_text(
            encoding="utf-8"
        )
    )
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"{schema['$id']}#/$defs/IntegratedTravelContext",
        },
        registry=registry,
        format_checker=FormatChecker(),
    )
    validator.validate(fixture)
    provenance = fixture["_fixture_provenance"]
    assert provenance["source_record_id"] == "us7000tiib"
    assert provenance["captured_at"] == "2026-09-19T09:21:51Z"
    assert "public domain" in provenance["license"]
    assert provenance["redaction_note"]
