from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.context import current_correlation_id, current_request_id
from app.logging import get_logger


class ServiceError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
        field_errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.field_errors = field_errors or []


def error_body(error: ServiceError) -> dict[str, Any]:
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "field_errors": error.field_errors,
            "retryable": error.retryable,
            "retry_after_seconds": error.retry_after_seconds,
        },
        "meta": {
            "request_id": str(current_request_id()),
            "correlation_id": str(current_correlation_id()),
            "contract_version": "1.0.0",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "degraded_services": [],
        },
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
        headers = {}
        if exc.retry_after_seconds is not None:
            headers["Retry-After"] = str(exc.retry_after_seconds)
        headers["X-Error-Code"] = exc.code
        return JSONResponse(status_code=exc.status_code, content=error_body(exc), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        field_errors = [
            {
                "path": ".".join(str(part) for part in error["loc"] if part != "body"),
                "code": str(error["type"]).upper(),
            }
            for error in exc.errors()
        ]
        error = ServiceError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="The request did not match contract version 1.",
            field_errors=field_errors,
        )
        return JSONResponse(
            status_code=422,
            content=error_body(error),
            headers={"X-Error-Code": error.code},
        )

    # FastAPI raises its HTTPException subclass from endpoint code, while
    # Starlette raises the base class for router-level failures such as 404.
    # Register both so every HTTP error keeps the versioned error envelope.
    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _request: Request, exc: HTTPException | StarletteHTTPException
    ) -> JSONResponse:
        code = {
            401: "AUTHENTICATION_REQUIRED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
        }.get(exc.status_code, "INTERNAL_ERROR")
        error = ServiceError(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
        )
        headers = dict(exc.headers or {})
        headers["X-Error-Code"] = code
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(error),
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        get_logger().error(
            "unhandled_exception",
            status=500,
            error_code="INTERNAL_ERROR",
            exception_type=type(exc).__name__,
        )
        error = ServiceError(
            status_code=500,
            code="INTERNAL_ERROR",
            message="The service could not complete the request.",
        )
        return JSONResponse(
            status_code=500,
            content=error_body(error),
            headers={"X-Error-Code": error.code},
        )
