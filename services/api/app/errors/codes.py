"""The stable error vocabulary, and the HTTP status each code is served with.

These codes are part of the contract: clients branch on them, so adding one is a minor change and
renaming or removing one is breaking. The list is asserted against
`packages/contracts/jsonschema/common/enums.schema.json` in the test suite, so the two cannot drift.
"""

from __future__ import annotations

from enum import StrEnum
from http import HTTPStatus


class ErrorCode(StrEnum):
    """Mirror of `ErrorCode` in the shared contract."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_TIMEOUT = "DEPENDENCY_TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNSUPPORTED_COVERAGE = "UNSUPPORTED_COVERAGE"
    POLICY_VALIDATION_FAILED = "POLICY_VALIDATION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class FieldErrorCode(StrEnum):
    """Why one particular field was rejected."""

    REQUIRED = "REQUIRED"
    INVALID_FORMAT = "INVALID_FORMAT"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    TOO_LONG = "TOO_LONG"
    TOO_SHORT = "TOO_SHORT"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    UNSUPPORTED_VALUE = "UNSUPPORTED_VALUE"
    NOT_CONFIRMED = "NOT_CONFIRMED"
    INCONSISTENT = "INCONSISTENT"


#: One HTTP status per error code, so the same failure never arrives as 400 from one handler and
#: 422 from another.
STATUS_BY_CODE: dict[ErrorCode, HTTPStatus] = {
    ErrorCode.VALIDATION_ERROR: HTTPStatus.BAD_REQUEST,
    ErrorCode.AUTHENTICATION_REQUIRED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.FORBIDDEN: HTTPStatus.FORBIDDEN,
    ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.CONFLICT: HTTPStatus.CONFLICT,
    ErrorCode.IDEMPOTENCY_CONFLICT: HTTPStatus.CONFLICT,
    ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.DEPENDENCY_TIMEOUT: HTTPStatus.GATEWAY_TIMEOUT,
    ErrorCode.DEPENDENCY_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.INSUFFICIENT_EVIDENCE: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.UNSUPPORTED_COVERAGE: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.POLICY_VALIDATION_FAILED: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
}

#: Whether retrying the identical request could succeed. A client that retries a
#: `VALIDATION_ERROR` just burns quota; one that gives up on a `DEPENDENCY_TIMEOUT` loses an
#: answer it could have had.
RETRYABLE_CODES: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.RATE_LIMITED,
        ErrorCode.DEPENDENCY_TIMEOUT,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        ErrorCode.INTERNAL_ERROR,
    }
)
