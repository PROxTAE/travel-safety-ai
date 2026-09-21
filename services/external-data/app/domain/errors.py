"""Provider error contract.

The adapter-facing codes come from the module plan; the public-facing codes come
from 00_API_AND_DATA_CONTRACTS.md § 1. `ProviderError` is internal and must be
mapped before it can reach a consumer — a provider-specific message must never
leak out of the internal API.
"""

from __future__ import annotations

from enum import StrEnum


class ProviderErrorCode(StrEnum):
    PROVIDER_AUTH = "PROVIDER_AUTH"
    PROVIDER_QUOTA = "PROVIDER_QUOTA"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_SCHEMA_CHANGED = "PROVIDER_SCHEMA_CHANGED"
    PROVIDER_OUTAGE = "PROVIDER_OUTAGE"
    OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"
    LICENSE_RESTRICTION = "LICENSE_RESTRICTION"


class ApiErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_TIMEOUT = "DEPENDENCY_TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    UNSUPPORTED_COVERAGE = "UNSUPPORTED_COVERAGE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ProviderError(Exception):
    """Raised by adapters and the shared transport. Never serialised as-is."""

    def __init__(
        self,
        code: ProviderErrorCode,
        provider_id: str,
        *,
        message: str = "",
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(f"{provider_id}: {code}")
        self.code = code
        self.provider_id = provider_id
        self.message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.http_status = http_status


# How an internal provider failure is presented to a consumer. The mapping is
# deliberately lossy: the consumer learns what it can do about the failure, not
# which provider produced it or why.
_PROVIDER_TO_API: dict[ProviderErrorCode, tuple[ApiErrorCode, int, bool]] = {
    # provider code                  -> (api code, http status, retryable)
    ProviderErrorCode.PROVIDER_AUTH: (ApiErrorCode.DEPENDENCY_UNAVAILABLE, 503, False),
    ProviderErrorCode.PROVIDER_QUOTA: (ApiErrorCode.DEPENDENCY_UNAVAILABLE, 503, True),
    ProviderErrorCode.PROVIDER_RATE_LIMIT: (ApiErrorCode.RATE_LIMITED, 429, True),
    ProviderErrorCode.PROVIDER_TIMEOUT: (ApiErrorCode.DEPENDENCY_TIMEOUT, 504, True),
    ProviderErrorCode.PROVIDER_SCHEMA_CHANGED: (
        ApiErrorCode.DEPENDENCY_UNAVAILABLE,
        503,
        False,
    ),
    ProviderErrorCode.PROVIDER_OUTAGE: (ApiErrorCode.DEPENDENCY_UNAVAILABLE, 503, True),
    ProviderErrorCode.OUTSIDE_COVERAGE: (ApiErrorCode.UNSUPPORTED_COVERAGE, 422, False),
    ProviderErrorCode.LICENSE_RESTRICTION: (
        ApiErrorCode.UNSUPPORTED_COVERAGE,
        422,
        False,
    ),
}

# Safe, user-facing text. Never includes the provider name or its raw message:
# PROVIDER_AUTH in particular must not tell a caller that our key is wrong.
_SAFE_MESSAGE: dict[ProviderErrorCode, str] = {
    ProviderErrorCode.PROVIDER_AUTH: "This data source is not configured in this deployment",
    ProviderErrorCode.PROVIDER_QUOTA: "This data source is temporarily unavailable",
    ProviderErrorCode.PROVIDER_RATE_LIMIT: "Too many requests to this data source",
    ProviderErrorCode.PROVIDER_TIMEOUT: "This data source did not respond in time",
    ProviderErrorCode.PROVIDER_SCHEMA_CHANGED: "This data source returned an unexpected response",
    ProviderErrorCode.PROVIDER_OUTAGE: "This data source is temporarily unavailable",
    ProviderErrorCode.OUTSIDE_COVERAGE: "This request is outside the supported coverage",
    ProviderErrorCode.LICENSE_RESTRICTION: "This data cannot be provided under the source licence",
}


def map_provider_error(error: ProviderError) -> tuple[ApiErrorCode, int, str, bool]:
    """(api_code, http_status, safe_message, retryable) for a provider failure."""
    api_code, status, retryable = _PROVIDER_TO_API[error.code]
    return api_code, status, _SAFE_MESSAGE[error.code], retryable
