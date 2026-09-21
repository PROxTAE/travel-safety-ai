from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

from app.contracts import TravelWindow

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


def test_m05_canonical_travel_window_is_accepted_by_m06() -> None:
    fixture_path = (
        REPOSITORY_ROOT
        / "packages"
        / "contracts"
        / "examples"
        / "real-sanitized"
        / "integrated-travel-context.bangkok-route.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    window = TravelWindow.model_validate(fixture["value"]["travel_window"])

    assert window.timezone == "Asia/Bangkok"


def test_travel_window_rejects_unknown_iana_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone must be an IANA zone"):
        TravelWindow.model_validate(
            {
                "starts_at": "2026-09-19T00:00:00Z",
                "ends_at": "2026-09-19T01:00:00Z",
                "timezone": "Mars/Olympus",
            }
        )


def test_m06_travel_window_schema_tracks_the_canonical_contract() -> None:
    risk_schema = json.loads(
        (
            REPOSITORY_ROOT
            / "packages"
            / "contracts"
            / "jsonschema"
            / "risk-knowledge"
            / "risk-knowledge-contract.schema.json"
        ).read_text(encoding="utf-8")
    )
    canonical_context = json.loads(
        (
            REPOSITORY_ROOT
            / "packages"
            / "contracts"
            / "jsonschema"
            / "common"
            / "integrated-travel-context.schema.json"
        ).read_text(encoding="utf-8")
    )
    primitives = json.loads(
        (
            REPOSITORY_ROOT
            / "packages"
            / "contracts"
            / "jsonschema"
            / "common"
            / "primitives.schema.json"
        ).read_text(encoding="utf-8")
    )

    consumer_window = risk_schema["$defs"]["IntegratedTravelContext"]["properties"]["travel_window"]
    canonical_window = canonical_context["$defs"]["TravelWindow"]

    assert consumer_window["required"] == canonical_window["required"]
    assert consumer_window["properties"]["timezone"] == primitives["$defs"]["Timezone"]
