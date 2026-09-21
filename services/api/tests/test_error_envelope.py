"""Error handling.

Every failure leaves this service as the same envelope, with a stable code and a message a user
could act on. The tests that matter most are the ones asserting what is *not* in the body: a
handler that leaks a stack trace or a rejected value is the difference between a 500 and an
incident.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.errors.codes import ErrorCode, FieldErrorCode
from app.errors.exceptions import (
    Conflict,
    FieldError,
    IdempotencyConflict,
    NotFound,
    RateLimited,
    ValidationFailed,
)


class EchoBody(BaseModel):
    """Declared at module level.

    This module uses postponed annotations, so FastAPI resolves a handler's type hints against the
    module namespace. A model defined inside the fixture would not be found there.
    """

    name: str
    count: int


@pytest.fixture
def app_with_failing_routes(app: FastAPI) -> FastAPI:
    """Routes that fail in every way the service has to survive."""

    @app.post("/_test/echo")
    async def echo(body: EchoBody) -> dict[str, str]:
        return {"name": body.name}

    @app.get("/_test/not-found")
    async def not_found() -> None:
        raise NotFound

    @app.get("/_test/conflict")
    async def conflict() -> None:
        raise Conflict

    @app.get("/_test/idempotency")
    async def idempotency() -> None:
        raise IdempotencyConflict

    @app.get("/_test/rate-limited")
    async def rate_limited() -> None:
        raise RateLimited(retry_after_seconds=30)

    @app.get("/_test/field-errors")
    async def field_errors() -> None:
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="destination.confirmed_by_user",
                    code=FieldErrorCode.NOT_CONFIRMED,
                    message="Confirm the destination pin before saving the trip.",
                )
            ]
        )

    @app.get("/_test/boom")
    async def boom() -> None:
        # Carries exactly the kind of detail that must never reach a client.
        raise RuntimeError(
            "psycopg.OperationalError: connection to server at postgres:5432 failed: "
            'password authentication failed for user "smart_travel"'
        )

    return app


async def test_expected_error_uses_the_contract_envelope(
    app_with_failing_routes: FastAPI, client: httpx.AsyncClient
) -> None:
    response = await client.get("/_test/not-found")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == ErrorCode.NOT_FOUND.value
    assert payload["error"]["retryable"] is False
    assert payload["meta"]["contract_version"] == "1.0.0"
    assert payload["meta"]["request_id"]


async def test_unexpected_exception_never_leaks_internals(
    app_with_failing_routes: FastAPI, client: httpx.AsyncClient
) -> None:
    """The response says what the user can do; the detail goes to the log under the request id."""
    response = await client.get("/_test/boom")
    body = response.text

    assert response.status_code == 500
    assert response.json()["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    leaks = ("psycopg", "postgres:5432", "password authentication", "Traceback", "RuntimeError")
    for leak in leaks:
        assert leak not in body, f"internal detail leaked to the client: {leak}"


async def test_request_validation_reports_paths_without_echoing_values(
    app_with_failing_routes: FastAPI, client: httpx.AsyncClient
) -> None:
    """A rejected value on this API can be a coordinate or a medical note."""
    response = await client.post(
        "/_test/echo", json={"name": "somewhere sensitive", "count": "not-a-number"}
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == ErrorCode.VALIDATION_ERROR.value

    paths = {item["path"] for item in payload["error"]["field_errors"]}
    assert "count" in paths
    assert "somewhere sensitive" not in response.text
    assert "not-a-number" not in response.text


async def test_missing_field_is_reported_as_required(
    app_with_failing_routes: FastAPI, client: httpx.AsyncClient
) -> None:
    response = await client.post("/_test/echo", json={"count": 1})

    errors = {item["path"]: item["code"] for item in response.json()["error"]["field_errors"]}
    assert errors["name"] == FieldErrorCode.REQUIRED.value


async def test_field_errors_survive_to_the_client(
    app_with_failing_routes: FastAPI, client: httpx.AsyncClient
) -> None:
    response = await client.get("/_test/field-errors")

    field_error = response.json()["error"]["field_errors"][0]
    assert field_error["path"] == "destination.confirmed_by_user"
    assert field_error["code"] == FieldErrorCode.NOT_CONFIRMED.value


async def test_rate_limit_tells_the_client_when_to_come_back(
    app_with_failing_routes: FastAPI, client: httpx.AsyncClient
) -> None:
    response = await client.get("/_test/rate-limited")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.json()["error"]["retry_after_seconds"] == 30
    assert response.json()["error"]["retryable"] is True


async def test_idempotency_conflict_is_distinct_from_plain_conflict(
    app_with_failing_routes: FastAPI, client: httpx.AsyncClient
) -> None:
    """Both are 409; only the code tells the client whether to retry with a new key or re-read."""
    conflict = await client.get("/_test/conflict")
    idempotency = await client.get("/_test/idempotency")

    assert conflict.status_code == idempotency.status_code == 409
    assert conflict.json()["error"]["code"] == ErrorCode.CONFLICT.value
    assert idempotency.json()["error"]["code"] == ErrorCode.IDEMPOTENCY_CONFLICT.value


async def test_unknown_route_uses_the_same_envelope(client: httpx.AsyncClient) -> None:
    """Starlette's own 404 is translated too, so clients need one error branch, not two."""
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == ErrorCode.NOT_FOUND.value
    assert "meta" in payload


async def test_method_not_allowed_uses_the_same_envelope(client: httpx.AsyncClient) -> None:
    response = await client.post("/health/live")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR.value


async def test_authentication_error_advertises_the_scheme(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    from app.errors.exceptions import AuthenticationRequired

    @app.get("/_test/unauthenticated")
    async def unauthenticated() -> None:
        raise AuthenticationRequired

    response = await client.get("/_test/unauthenticated")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_response_that_violates_the_contract_is_withheld(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Serving a malformed safety answer is worse than serving none.

    A client renders whatever arrives, and a dropped `limitations` list reads as reassurance.
    """
    from pydantic import ValidationError

    class Recommendation(BaseModel):
        action_code: str
        risk_level: str

    @app.get("/_test/bad-response")
    async def bad_response() -> None:
        try:
            Recommendation.model_validate({"action_code": "NORMAL"})
        except ValidationError:
            raise

    response = await client.get("/_test/bad-response")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert "risk_level" not in response.text


def test_every_contract_error_code_has_a_status_and_a_retry_stance() -> None:
    """A code with no mapping would fall through to 500 and mislead the client."""
    from app.errors.codes import RETRYABLE_CODES, STATUS_BY_CODE

    for code in ErrorCode:
        assert code in STATUS_BY_CODE, f"{code} has no HTTP status"

    assert ErrorCode.VALIDATION_ERROR not in RETRYABLE_CODES
    assert ErrorCode.DEPENDENCY_TIMEOUT in RETRYABLE_CODES
