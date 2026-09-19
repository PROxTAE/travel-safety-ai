from __future__ import annotations

import re
import secrets
from uuid import UUID

from fastapi import Request

from app.errors import ServiceError

TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def _valid_canonical_uuid(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return str(UUID(value)) == value.lower()
    except ValueError:
        return False


async def require_internal_auth(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.internal_auth_configured:
        raise ServiceError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="Internal service authentication is not configured.",
            retryable=False,
        )

    authorization = request.headers.get("Authorization")
    expected = settings.internal_api_token.get_secret_value()
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if (
        not authorization
        or not authorization.startswith("Bearer ")
        or not secrets.compare_digest(supplied, expected)
    ):
        raise ServiceError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message="A valid service credential is required.",
        )

    field_errors: list[dict[str, str]] = []
    for header in ("X-Request-ID", "X-Correlation-ID"):
        if not _valid_canonical_uuid(request.headers.get(header)):
            field_errors.append({"path": f"headers.{header}", "code": "INVALID_UUID"})
    if request.headers.get("X-Contract-Version") != "1":
        field_errors.append({"path": "headers.X-Contract-Version", "code": "UNSUPPORTED"})
    traceparent = request.headers.get("traceparent", "").lower()
    if not TRACEPARENT_RE.fullmatch(traceparent):
        field_errors.append({"path": "headers.traceparent", "code": "INVALID_FORMAT"})
    if field_errors:
        raise ServiceError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Required service headers are missing or invalid.",
            field_errors=field_errors,
        )
