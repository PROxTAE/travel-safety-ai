"""Exception handlers.

Every path out of this service ends here, and every one of them produces the same envelope. That
matters for two reasons: a client can write one error branch instead of three, and an unexpected
exception cannot leak a stack trace, a SQL fragment or a connection string to the caller. The
detail still exists — it goes to the log, keyed by the request id the caller was given — but the
response says only what a user can act on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from app.errors.codes import RETRYABLE_CODES, STATUS_BY_CODE, ErrorCode, FieldErrorCode
from app.errors.exceptions import AppError
from app.middleware.access_log import route_template
from app.middleware.request_context import current_correlation_id, current_request_id
from app.observability.logging import get_logger
from app.observability.metrics import observe_error
from app.schemas.envelope import ErrorBody, ErrorResponse, FieldErrorModel, build_meta

if TYPE_CHECKING:
    from app.settings import Settings

logger = get_logger(__name__)

#: Maps pydantic's machine-readable error type onto the contract's field error vocabulary. Anything
#: unrecognised becomes INVALID_FORMAT, which is true for every remaining case and says nothing the
#: client could not work out from the path.
_PYDANTIC_TO_FIELD_CODE: dict[str, FieldErrorCode] = {
    "missing": FieldErrorCode.REQUIRED,
    "string_too_long": FieldErrorCode.TOO_LONG,
    "string_too_short": FieldErrorCode.TOO_SHORT,
    "too_long": FieldErrorCode.TOO_LONG,
    "too_short": FieldErrorCode.TOO_SHORT,
    "greater_than": FieldErrorCode.OUT_OF_RANGE,
    "greater_than_equal": FieldErrorCode.OUT_OF_RANGE,
    "less_than": FieldErrorCode.OUT_OF_RANGE,
    "less_than_equal": FieldErrorCode.OUT_OF_RANGE,
    "extra_forbidden": FieldErrorCode.UNKNOWN_FIELD,
    "enum": FieldErrorCode.UNSUPPORTED_VALUE,
    "literal_error": FieldErrorCode.UNSUPPORTED_VALUE,
    "value_error": FieldErrorCode.INCONSISTENT,
}

#: HTTP statuses Starlette raises on its own, mapped onto contract codes.
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.AUTHENTICATION_REQUIRED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.VALIDATION_ERROR,
    409: ErrorCode.CONFLICT,
    412: ErrorCode.CONFLICT,
    413: ErrorCode.VALIDATION_ERROR,
    415: ErrorCode.VALIDATION_ERROR,
    422: ErrorCode.VALIDATION_ERROR,
    428: ErrorCode.CONFLICT,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    502: ErrorCode.DEPENDENCY_UNAVAILABLE,
    503: ErrorCode.DEPENDENCY_UNAVAILABLE,
    504: ErrorCode.DEPENDENCY_TIMEOUT,
}

#: Safe replacements for the wording Starlette and FastAPI supply by default.
_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "Some fields in the request are invalid.",
    ErrorCode.AUTHENTICATION_REQUIRED: "Sign in to continue.",
    ErrorCode.FORBIDDEN: "This action is not permitted.",
    ErrorCode.NOT_FOUND: "Not found.",
    ErrorCode.CONFLICT: "The resource changed since you last read it.",
    ErrorCode.RATE_LIMITED: "Too many requests. Try again shortly.",
    ErrorCode.DEPENDENCY_TIMEOUT: "A service this request depends on did not answer in time.",
    ErrorCode.DEPENDENCY_UNAVAILABLE: "A service this request depends on is unavailable.",
    ErrorCode.INTERNAL_ERROR: "Something went wrong on our side.",
}


def _location_to_path(location: tuple[int | str, ...]) -> str:
    """Turn pydantic's `("body", "origin", "coordinates", 0)` into `origin.coordinates[0]`.

    The leading `body` / `query` / `path` marker is dropped: the client knows where it put the
    value, and keeping it makes the path harder to match against the request that was sent.
    """
    parts = [part for part in location if part not in {"body", "query", "path", "header"}]
    rendered = ""
    for part in parts:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}" if rendered else str(part)
    return rendered or "<request>"


def _field_errors(errors: list[dict[str, Any]]) -> list[FieldErrorModel]:
    """Describe which fields failed, without echoing what was sent.

    pydantic's `msg` is safe wording about the rule that was broken, but its `input` is the
    rejected value itself — which for this API can be a coordinate or a medical note — so only the
    message is carried over.
    """
    return [
        FieldErrorModel(
            path=_location_to_path(tuple(error.get("loc", ()))),
            code=_PYDANTIC_TO_FIELD_CODE.get(
                str(error.get("type", "")), FieldErrorCode.INVALID_FORMAT
            ),
            message=str(error.get("msg"))[:512] if error.get("msg") else None,
        )
        for error in errors
    ]


def _respond(
    *,
    code: ErrorCode,
    message: str,
    settings: Settings,
    field_errors: list[FieldErrorModel] | None = None,
    retry_after_seconds: int | None = None,
    status_override: int | None = None,
) -> ORJSONResponse:
    status = status_override or int(STATUS_BY_CODE[code])
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            field_errors=field_errors or [],
            retryable=code in RETRYABLE_CODES,
            retry_after_seconds=retry_after_seconds,
        ),
        meta=build_meta(
            request_id=current_request_id(),
            correlation_id=current_correlation_id(),
            contract_version=settings.contract_version,
        ),
    )

    headers: dict[str, str] = {}
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(retry_after_seconds)
    if code is ErrorCode.AUTHENTICATION_REQUIRED:
        headers["WWW-Authenticate"] = "Bearer"

    return ORJSONResponse(
        status_code=status,
        content=payload.model_dump(mode="json"),
        headers=headers or None,
    )


def register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    """Wire every exception type onto the envelope."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> ORJSONResponse:
        logger.warning(
            "request_failed",
            event_type="request_failed",
            error_code=exc.code.value,
            route=route_template(request.scope),
            **exc.log_context,
        )
        observe_error(route=route_template(request.scope), error_code=exc.code.value)
        return _respond(
            code=exc.code,
            message=exc.message,
            settings=settings,
            field_errors=[
                FieldErrorModel(path=item.path, code=item.code, message=item.message)
                for item in exc.field_errors
            ],
            retry_after_seconds=exc.retry_after_seconds,
            status_override=exc.status_override,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> ORJSONResponse:
        route = route_template(request.scope)
        field_errors = _field_errors(list(exc.errors()))
        logger.info(
            "request_rejected",
            event_type="request_rejected",
            error_code=ErrorCode.VALIDATION_ERROR.value,
            route=route,
            # Paths only. The values that failed are exactly the ones worth not logging.
            invalid_paths=[item.path for item in field_errors],
        )
        observe_error(route=route, error_code=ErrorCode.VALIDATION_ERROR.value)
        return _respond(
            code=ErrorCode.VALIDATION_ERROR,
            message=_DEFAULT_MESSAGES[ErrorCode.VALIDATION_ERROR],
            settings=settings,
            field_errors=field_errors,
        )

    @app.exception_handler(ValidationError)
    async def handle_response_validation(request: Request, exc: ValidationError) -> ORJSONResponse:
        """A response that does not match the contract is withheld.

        Serving a malformed safety answer is worse than serving none: the client would render
        whatever arrived, and a missing `risk_level` or a dropped `limitations` list looks exactly
        like reassurance.
        """
        route = route_template(request.scope)
        logger.error(
            "response_contract_violation",
            event_type="response_contract_violation",
            route=route,
            error_count=exc.error_count(),
            invalid_paths=[_location_to_path(tuple(err.get("loc", ()))) for err in exc.errors()],
        )
        observe_error(route=route, error_code=ErrorCode.INTERNAL_ERROR.value)
        return _respond(
            code=ErrorCode.INTERNAL_ERROR,
            message="The answer could not be verified and was withheld.",
            settings=settings,
            status_override=502,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> ORJSONResponse:
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        route = route_template(request.scope)
        logger.info(
            "request_failed",
            event_type="request_failed",
            error_code=code.value,
            route=route,
            status=exc.status_code,
        )
        observe_error(route=route, error_code=code.value)
        # exc.detail is replaced: Starlette's defaults are fine, but a detail set deep in a
        # dependency is not guaranteed to be safe to show.
        return _respond(
            code=code,
            message=_DEFAULT_MESSAGES.get(code, "The request could not be completed."),
            settings=settings,
            status_override=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> ORJSONResponse:
        route = route_template(request.scope)
        logger.exception(
            "unhandled_exception",
            event_type="unhandled_exception",
            route=route,
            exception_type=type(exc).__name__,
        )
        observe_error(route=route, error_code=ErrorCode.INTERNAL_ERROR.value)
        return _respond(
            code=ErrorCode.INTERNAL_ERROR,
            message=_DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
            settings=settings,
        )
