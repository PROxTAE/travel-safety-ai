"""Application errors.

Every failure a handler raises deliberately is one of these. They carry the contract error code,
an already-user-safe message and optional field errors; the handler turns them into the response
envelope without having to guess a status or invent wording.

The message is written for the person who will read it. It must never contain a stack trace, SQL,
a connection string, an internal host name, a provider credential, or the value of a field that is
itself sensitive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.errors.codes import ErrorCode, FieldErrorCode


@dataclass(frozen=True, slots=True)
class FieldError:
    """One rejected field."""

    path: str
    code: FieldErrorCode
    message: str | None = None


class AppError(Exception):
    """Base class for every deliberate failure."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    default_message = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        field_errors: list[FieldError] | None = None,
        retry_after_seconds: int | None = None,
        # Context is for the log line, never for the response body.
        log_context: dict[str, object] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.field_errors = field_errors or []
        self.retry_after_seconds = retry_after_seconds
        self.log_context = log_context or {}
        super().__init__(self.message)


class ValidationFailed(AppError):
    code = ErrorCode.VALIDATION_ERROR
    default_message = "Some fields in the request are invalid."


class AuthenticationRequired(AppError):
    code = ErrorCode.AUTHENTICATION_REQUIRED
    default_message = "Sign in to continue."


class Forbidden(AppError):
    code = ErrorCode.FORBIDDEN
    default_message = "This action is not permitted."


class NotFound(AppError):
    """Also raised for a resource that exists but belongs to someone else.

    Answering 403 there would confirm the id exists, which lets an attacker enumerate other
    people's trips. From outside, "not yours" and "not there" look the same on purpose.
    """

    code = ErrorCode.NOT_FOUND
    default_message = "Not found."


class Conflict(AppError):
    code = ErrorCode.CONFLICT
    default_message = "The resource changed since you last read it."


class IdempotencyConflict(AppError):
    code = ErrorCode.IDEMPOTENCY_CONFLICT
    default_message = (
        "This idempotency key was already used for a different request. Use a new key."
    )


class RateLimited(AppError):
    code = ErrorCode.RATE_LIMITED
    default_message = "Too many requests. Try again shortly."


@dataclass(frozen=True, slots=True)
class _Dependency:
    """Which dependency failed, for the log and for `meta.degraded_services`."""

    name: str


class DependencyTimeout(AppError):
    code = ErrorCode.DEPENDENCY_TIMEOUT
    default_message = "A service this request depends on did not answer in time."

    def __init__(self, dependency: str, **kwargs: object) -> None:
        self.dependency = _Dependency(dependency)
        super().__init__(**kwargs)  # type: ignore[arg-type]


class DependencyUnavailable(AppError):
    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    default_message = "A service this request depends on is unavailable."

    def __init__(self, dependency: str, **kwargs: object) -> None:
        self.dependency = _Dependency(dependency)
        super().__init__(**kwargs)  # type: ignore[arg-type]


class UnsupportedCoverage(AppError):
    """The request is well-formed but no real data source covers it.

    Raised instead of guessing. A travel mode with no provider in that region is reported as
    unsupported; it is never assessed on the assumption that "no data" means "no problem".
    """

    code = ErrorCode.UNSUPPORTED_COVERAGE
    default_message = "This is not supported for the selected location or travel mode."


class InsufficientEvidence(AppError):
    code = ErrorCode.INSUFFICIENT_EVIDENCE
    default_message = "There is not enough reliable information to answer safely."


class PolicyValidationFailed(AppError):
    code = ErrorCode.POLICY_VALIDATION_FAILED
    default_message = "This action is not allowed by the safety policy."


class InternalError(AppError):
    code = ErrorCode.INTERNAL_ERROR
    default_message = "Something went wrong on our side."


@dataclass(frozen=True, slots=True)
class ProblemContext:
    """Extra detail attached to the log line for a failure, never to the response."""

    request_id: str
    correlation_id: str
    route: str
    extra: dict[str, object] = field(default_factory=dict)
