"""Checks on the public OpenAPI document itself.

Redocly lints the document's syntax and style. These tests assert the things that are specific to
this product and would otherwise only be caught by a careful reviewer: that every endpoint the
contract document promises exists, that authentication is on by default, that mutating operations
accept an idempotency key, and that safety-bearing responses keep their provenance.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from conftest import BUNDLED_OPENAPI, CONTRACTS

SOURCE_OPENAPI = CONTRACTS / "openapi" / "public-api.yaml"

# Section 4 of IMPLEMENTATION_PLANS/00_API_AND_DATA_CONTRACTS.md, as (method, path) pairs.
REQUIRED_OPERATIONS = [
    ("get", "/api/v1/me"),
    ("patch", "/api/v1/me"),
    ("get", "/api/v1/me/emergency-profile"),
    ("put", "/api/v1/me/emergency-profile"),
    ("post", "/api/v1/consents"),
    ("get", "/api/v1/locations/search"),
    ("post", "/api/v1/trips"),
    ("get", "/api/v1/trips/{trip_id}"),
    ("patch", "/api/v1/trips/{trip_id}"),
    ("delete", "/api/v1/trips/{trip_id}"),
    ("post", "/api/v1/trips/{trip_id}/assessments"),
    ("get", "/api/v1/runs/{request_id}"),
    ("get", "/api/v1/runs/{request_id}/events"),
    ("get", "/api/v1/recommendations/{recommendation_id}"),
    ("post", "/api/v1/trips/{trip_id}/apply-route"),
    ("get", "/api/v1/safety/events"),
    ("get", "/api/v1/conversations"),
    ("post", "/api/v1/conversations/{conversation_id}/messages"),
    ("post", "/api/v1/feedback"),
    ("post", "/api/v1/alert-subscriptions"),
    ("delete", "/api/v1/alert-subscriptions/{subscription_id}"),
    ("get", "/api/v1/emergency/contacts"),
    ("get", "/api/v1/emergency/nearby"),
]

PUBLIC_OPERATIONS = {"healthLive", "healthReady"}


@pytest.fixture(scope="session")
def spec() -> dict[str, Any]:
    if not BUNDLED_OPENAPI.exists():
        pytest.fail(
            "Bundled OpenAPI is missing. Run:\n  cd packages/contracts && npm run bundle"
        )
    return yaml.safe_load(BUNDLED_OPENAPI.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def source_spec() -> dict[str, Any]:
    return yaml.safe_load(SOURCE_OPENAPI.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("method", "path"), REQUIRED_OPERATIONS)
def test_contract_document_endpoints_all_exist(
    spec: dict[str, Any], method: str, path: str
) -> None:
    assert path in spec["paths"], f"{path} is missing from the public contract."
    assert method in spec["paths"][path], f"{method.upper()} {path} is missing."


def test_contract_version_is_semver(spec: dict[str, Any]) -> None:
    major, minor, patch = spec["info"]["version"].split(".")
    assert all(part.isdigit() for part in (major, minor, patch))


def test_authentication_is_on_by_default(spec: dict[str, Any]) -> None:
    """Security is declared once at the document level so a new endpoint is protected by
    omission rather than by remembering to add it."""
    assert spec["security"] == [{"bearerAuth": []}]


def test_only_health_endpoints_opt_out_of_authentication(spec: dict[str, Any]) -> None:
    unauthenticated = [
        operation.get("operationId", f"{method.upper()} {path}")
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in {"get", "post", "put", "patch", "delete"} and operation.get("security") == []
    ]
    assert set(unauthenticated) == PUBLIC_OPERATIONS, (
        f"Unexpected unauthenticated operations: {sorted(set(unauthenticated) - PUBLIC_OPERATIONS)}"
    )


def test_mutating_operations_are_safe_to_retry(source_spec: dict[str, Any]) -> None:
    """A retried request must not create a second trip, run or subscription.

    Two mechanisms count. `Idempotency-Key` makes a retry return the original result; `If-Match`
    makes a replay fail with 412 because the revision has already moved. An operation offering
    neither can be duplicated by a flaky network, which for `assessments` means two runs and two
    sets of provider calls.
    """
    missing: list[str] = []

    for path, item in source_spec["paths"].items():
        for method, operation in item.items():
            if method not in {"post", "put", "patch"}:
                continue
            refs = {
                parameter.get("$ref", "")
                for parameter in operation.get("parameters", [])
                if isinstance(parameter, dict)
            }
            guarded = refs & {
                "#/components/parameters/IdempotencyKey",
                "#/components/parameters/IfMatch",
            }
            if not guarded:
                missing.append(operation.get("operationId", f"{method} {path}"))

    assert not missing, f"Mutating operations that a retry could duplicate: {missing}"


def test_trip_mutation_requires_if_match(source_spec: dict[str, Any]) -> None:
    """Optimistic concurrency is the only thing stopping a second tab from overwriting a change
    it never saw."""
    for path, method in [("/api/v1/trips/{trip_id}", "patch"), ("/api/v1/trips/{trip_id}/apply-route", "post")]:
        operation = source_spec["paths"][path][method]
        refs = {parameter.get("$ref", "") for parameter in operation["parameters"]}
        assert "#/components/parameters/IfMatch" in refs, f"{method.upper()} {path} must require If-Match"
        assert "412" in operation["responses"], f"{method.upper()} {path} must document 412"


def test_assessment_start_is_asynchronous(spec: dict[str, Any]) -> None:
    """A safety assessment calls several providers; holding the request open would time out in the
    browser long before the answer is ready."""
    responses = spec["paths"]["/api/v1/trips/{trip_id}/assessments"]["post"]["responses"]
    assert "202" in responses
    assert "200" not in responses


def test_sse_stream_is_event_stream(spec: dict[str, Any]) -> None:
    operation = spec["paths"]["/api/v1/runs/{request_id}/events"]["get"]
    assert "text/event-stream" in operation["responses"]["200"]["content"]
    header_names = {
        parameter["name"]
        for parameter in operation["parameters"]
        if isinstance(parameter, dict) and "name" in parameter
    }
    assert "Last-Event-ID" in header_names, "Reconnect without Last-Event-ID loses terminal events."


def test_run_stages_match_the_contract_document(spec: dict[str, Any]) -> None:
    expected = [
        "VALIDATING",
        "FETCHING_EXTERNAL_DATA",
        "INTEGRATING_DATA",
        "ASSESSING_RISK",
        "RETRIEVING_GUIDANCE",
        "EVALUATING_ROUTES",
        "MAKING_DECISION",
        "EXPLAINING",
        "FORMATTING_RESPONSE",
    ]
    assert spec["components"]["schemas"]["RunStage"]["enum"] == expected


def test_recommendation_keeps_provenance_required(spec: dict[str, Any]) -> None:
    required = set(spec["components"]["schemas"]["RecommendationResponse"]["required"])
    for field in ("sources", "freshness", "limitations", "degraded_services", "versions"):
        assert field in required, f"RecommendationResponse must always carry {field}"


def test_request_bodies_reject_unknown_fields(spec: dict[str, Any]) -> None:
    """Input is closed at the boundary: an unrecognised field is a client bug or an attack, and
    silently ignoring it hides both."""
    open_bodies: list[str] = []

    for name, schema in spec["components"]["schemas"].items():
        if not name.endswith("Request"):
            continue
        if schema.get("additionalProperties") is not False:
            open_bodies.append(name)

    assert not open_bodies, f"Request schemas must set additionalProperties: false — {open_bodies}"


def test_error_responses_are_documented_for_every_authenticated_operation(
    source_spec: dict[str, Any],
) -> None:
    missing: list[str] = []

    for path, item in source_spec["paths"].items():
        if path.startswith("/health"):
            continue
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if "401" not in operation.get("responses", {}):
                missing.append(operation.get("operationId", f"{method} {path}"))

    assert not missing, f"Operations that do not document 401: {missing}"
