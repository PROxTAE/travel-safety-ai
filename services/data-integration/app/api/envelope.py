"""Shared internal envelope metadata and safe errors."""

from datetime import UTC, datetime
from typing import Any

from fastapi.responses import JSONResponse

from app.observability.context import correlation_id, request_id
from app.settings import get_settings


def meta() -> dict[str, Any]:
    return {
        "request_id": request_id.get(),
        "correlation_id": correlation_id.get(),
        "contract_version": get_settings().contract_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "degraded_services": [],
    }


def success(data: Any) -> dict[str, Any]:
    return {"data": data, "meta": meta()}


def error(
    code: str, message: str, status: int, field_errors: list[dict[str, str]] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "field_errors": field_errors or [],
                "retryable": status >= 500,
                "retry_after_seconds": None,
            },
            "meta": meta(),
        },
    )
