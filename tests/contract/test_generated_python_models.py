"""Consumer-side check: the generated Pydantic models accept what the contract promises.

A schema can be valid and still generate models a service cannot use — a pattern that will not
apply to a typed field, a nullable that came out required, an enum that lost a member. These tests
exercise the generated code the way a service does, so that breakage shows up here rather than in
a request handler.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from conftest import COMMON_SCHEMAS


def _example(name: str) -> dict[str, Any]:
    path = COMMON_SCHEMAS.parents[1] / "examples" / name
    return json.loads(path.read_text(encoding="utf-8"))["value"]


def test_generated_models_import(generated_models: Any) -> None:
    assert hasattr(generated_models, "RecommendationResponse")
    assert hasattr(generated_models, "Trip")
    assert hasattr(generated_models, "RunState")


@pytest.mark.parametrize(
    ("fixture", "model_name"),
    [
        ("structural/trip.created.json", "Trip"),
        ("structural/run-state.degraded.json", "RunState"),
        ("structural/recommendation-response.avoid-official-closure.json", "RecommendationResponse"),
        ("real-sanitized/location-ref.open-meteo-bangkok.json", "LocationRef"),
    ],
)
def test_fixtures_load_into_generated_models(
    generated_models: Any, fixture: str, model_name: str
) -> None:
    model = getattr(generated_models, model_name)
    model.model_validate(_example(fixture))


def test_action_code_vocabulary_is_closed(generated_models: Any) -> None:
    """The product offers exactly four actions; a fifth would bypass every UI branch."""
    members = {member.value for member in generated_models.ActionCode}
    assert members == {"NORMAL", "CHANGE_ROUTE", "DELAY", "AVOID"}


def test_stable_error_codes_are_all_present(generated_models: Any) -> None:
    """Clients branch on these. Removing or renaming one is a breaking change."""
    expected = {
        "VALIDATION_ERROR",
        "AUTHENTICATION_REQUIRED",
        "FORBIDDEN",
        "NOT_FOUND",
        "CONFLICT",
        "IDEMPOTENCY_CONFLICT",
        "RATE_LIMITED",
        "DEPENDENCY_TIMEOUT",
        "DEPENDENCY_UNAVAILABLE",
        "INSUFFICIENT_EVIDENCE",
        "UNSUPPORTED_COVERAGE",
        "POLICY_VALIDATION_FAILED",
        "INTERNAL_ERROR",
    }
    assert {member.value for member in generated_models.ErrorCode} == expected


def test_transport_status_keeps_an_unknown_member() -> None:
    """Absence of a real-time feed must be expressible as UNKNOWN rather than as ON_TIME.

    Checked against the canonical schema rather than the generated public-API models: transport
    status is an internal entity that the public contract does not expose directly, so it is not
    reachable from the generated module.
    """
    enums = json.loads((COMMON_SCHEMAS / "enums.schema.json").read_text(encoding="utf-8"))
    members = set(enums["$defs"]["TransportStatusCode"]["enum"])
    assert {"ON_TIME", "UNKNOWN"} <= members


def test_recommendation_requires_its_safety_metadata(generated_models: Any) -> None:
    """Freshness, sources, limitations and degraded services are not optional decoration."""
    payload = _example("structural/recommendation-response.avoid-official-closure.json")

    for field in ("freshness", "sources", "limitations", "degraded_services"):
        stripped = {key: value for key, value in payload.items() if key != field}
        with pytest.raises(ValidationError):
            generated_models.RecommendationResponse.model_validate(stripped)


def test_route_exposure_must_state_whether_the_route_is_closed(generated_models: Any) -> None:
    payload = _example("structural/recommendation-response.avoid-official-closure.json")
    route = dict(payload["primary_route"])
    route["exposure"] = {key: value for key, value in route["exposure"].items() if key != "closed"}

    with pytest.raises(ValidationError):
        generated_models.RouteCandidate.model_validate(route)


def test_unconfirmed_location_is_still_representable(generated_models: Any) -> None:
    """The contract carries the confirmation flag; refusing unconfirmed input is the API's job,
    so the model must be able to hold `false` rather than making it unrepresentable."""
    payload = _example("real-sanitized/location-ref.open-meteo-bangkok.json")
    assert generated_models.LocationRef.model_validate(payload).confirmed_by_user is False


def test_coordinates_are_longitude_latitude() -> None:
    """Longitude first. Swapping the pair is the classic geospatial bug and puts a Bangkok trip in
    the Indian Ocean, so the schema bounds each element separately."""
    payload = _example("real-sanitized/location-ref.open-meteo-bangkok.json")
    longitude, latitude = payload["coordinates"]["coordinates"]
    assert longitude == pytest.approx(100.5014)
    assert latitude == pytest.approx(13.754)

    geojson = json.loads((COMMON_SCHEMAS / "geojson.schema.json").read_text(encoding="utf-8"))
    position = geojson["$defs"]["Position"]["prefixItems"]
    assert (position[0]["minimum"], position[0]["maximum"]) == (-180, 180)
    assert (position[1]["minimum"], position[1]["maximum"]) == (-90, 90)


def test_generated_python_does_not_enforce_coordinate_bounds(generated_models: Any) -> None:
    """A documented gap, pinned so it cannot be forgotten.

    datamodel-code-generator flattens `prefixItems` to a plain length-checked list, so the
    generated Pydantic model accepts a longitude of 1000. Range checking therefore has to happen at
    the API boundary, not by trusting the model. If a generator upgrade closes this gap, this test
    fails and the boundary validation can be revisited.
    """
    payload = json.loads(json.dumps(_example("real-sanitized/location-ref.open-meteo-bangkok.json")))
    payload["coordinates"]["coordinates"] = [1000.0, 13.754]
    generated_models.LocationRef.model_validate(payload)

    payload["coordinates"]["coordinates"] = [100.5014, 13.754, 12.0]
    with pytest.raises(ValidationError):
        generated_models.LocationRef.model_validate(payload)


def test_nullable_weather_values_stay_nullable(generated_models: Any) -> None:
    """A value the provider did not supply is null, never zero: 0 mm of rain and unknown rain are
    different facts and the contract must keep them apart."""
    schema = json.loads((COMMON_SCHEMAS / "weather.schema.json").read_text(encoding="utf-8"))
    point = schema["$defs"]["WeatherForecastPoint"]["properties"]

    for field in ("precipitation_mm", "wind_gust_kmh", "visibility_m", "temperature_c"):
        assert "null" in point[field]["type"], f"{field} must be nullable"
        assert field in schema["$defs"]["WeatherForecastPoint"]["required"], (
            f"{field} must be present even when null, so a consumer cannot mistake "
            "'absent' for 'not measured'"
        )


def test_generated_file_is_marked_as_generated() -> None:
    generated = (
        COMMON_SCHEMAS.parents[1]
        / "generated"
        / "python"
        / "smart_travel_contracts"
        / "public_api.py"
    )
    head = generated.read_text(encoding="utf-8")[:400]
    assert "DO NOT EDIT" in head
    assert "public-api.yaml" in head


def test_no_secret_shaped_string_in_contract_sources(contracts_root: Path) -> None:
    """Contracts and fixtures are read by everyone; a credential here would leak to all of them."""
    patterns = {
        "api key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
        "private key": re.compile(r"BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY"),
        "bearer token": re.compile(r"Bearer eyJ[A-Za-z0-9_-]{10,}"),
    }
    offenders: list[str] = []

    for path in contracts_root.rglob("*"):
        if not path.is_file() or "node_modules" in path.parts:
            continue
        if path.suffix not in {".json", ".yaml", ".yml", ".ts", ".mjs", ".md", ".py"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in patterns.items():
            if pattern.search(text):
                offenders.append(f"{path.name}: {label}")

    assert not offenders, f"Secret-shaped strings in contract sources: {offenders}"
