"""Standard success and error envelopes from 00_API_AND_DATA_CONTRACTS.md § 1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.domain.errors import ApiErrorCode, ProviderError, map_provider_error
from app.observability.context import correlation_id_var, request_id_var
from app.settings import get_settings


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    correlation_id: str
    contract_version: str
    generated_at: datetime
    degraded_services: list[str] = Field(default_factory=list)


class FieldError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    code: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ApiErrorCode
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)
    retryable: bool = False
    retry_after_seconds: float | None = None


def build_meta(degraded: list[str] | None = None) -> Meta:
    return Meta(
        request_id=request_id_var.get(),
        correlation_id=correlation_id_var.get(),
        contract_version=get_settings().contract_version,
        generated_at=datetime.now(UTC),
        degraded_services=degraded or [],
    )


def success(data: Any, *, degraded: list[str] | None = None) -> dict[str, Any]:
    return {
        "data": data,
        "meta": build_meta(degraded).model_dump(mode="json"),
    }


def error_response(
    code: ApiErrorCode,
    message: str,
    *,
    status_code: int,
    retryable: bool = False,
    retry_after_seconds: float | None = None,
    field_errors: list[FieldError] | None = None,
) -> JSONResponse:
    body = ErrorBody(
        code=code,
        message=message,
        field_errors=field_errors or [],
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )
    payload = {
        "error": body.model_dump(mode="json"),
        "meta": build_meta().model_dump(mode="json"),
    }
    headers = {}
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(int(retry_after_seconds))
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def provider_error_response(error: ProviderError) -> JSONResponse:
    """Map an internal provider failure to a safe consumer-facing error.

    The provider name and its raw message are dropped here on purpose - the
    module plan forbids provider-specific detail from reaching a consumer.
    """
    api_code, status, message, retryable = map_provider_error(error)
    return error_response(
        api_code,
        message,
        status_code=status,
        retryable=retryable,
        retry_after_seconds=error.retry_after_seconds,
    )
