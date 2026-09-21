"""The response envelope every endpoint answers with.

Defined here rather than imported from the generated contract models because these are the types
the handlers construct, and a hand-written model can carry the service's own invariants. The shapes
are asserted against the generated contract in the test suite, so they cannot drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.errors.codes import ErrorCode, FieldErrorCode

DataT = TypeVar("DataT")

DegradationReason = Literal[
    "TIMEOUT",
    "UNAVAILABLE",
    "RATE_LIMITED",
    "STALE_DATA",
    "PARTIAL_COVERAGE",
    "NOT_CONFIGURED",
    "SCHEMA_MISMATCH",
]


class DegradedService(BaseModel):
    """A dependency that answered late, partially or not at all.

    Reported rather than hidden: a user deciding whether to travel needs to know that the answer
    was assembled with something missing.
    """

    model_config = ConfigDict(frozen=True)

    service: Annotated[str, Field(max_length=64)]
    reason: DegradationReason
    since: datetime | None = None
    retrying: bool = False


class ResponseMeta(BaseModel):
    """Present on every response, success or failure."""

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    correlation_id: UUID | None = None
    contract_version: str
    generated_at: datetime
    degraded_services: list[DegradedService] = Field(default_factory=list)


class PageMeta(BaseModel):
    """Opaque cursor pagination. Clients pass the cursor back; they never construct one."""

    model_config = ConfigDict(frozen=True)

    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool = False


class FieldErrorModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Annotated[str, Field(max_length=256)]
    code: FieldErrorCode
    message: Annotated[str | None, Field(max_length=512)] = None


class ErrorBody(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ErrorCode
    message: Annotated[str, Field(max_length=1024)]
    field_errors: list[FieldErrorModel] = Field(default_factory=list)
    retryable: bool
    retry_after_seconds: Annotated[int | None, Field(ge=0, le=86400)] = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    error: ErrorBody
    meta: ResponseMeta


class DataResponse(BaseModel, Generic[DataT]):
    """A single resource."""

    model_config = ConfigDict(frozen=True)

    data: DataT
    meta: ResponseMeta


class ListResponse(BaseModel, Generic[DataT]):
    """A page of resources."""

    model_config = ConfigDict(frozen=True)

    data: list[DataT]
    meta: ResponseMeta
    page: PageMeta


def build_meta(
    *,
    request_id: UUID,
    correlation_id: UUID | None,
    contract_version: str,
    degraded_services: list[DegradedService] | None = None,
) -> ResponseMeta:
    """Assemble `meta` for one response.

    `generated_at` is stamped here rather than by the caller so that every response reports when
    the API produced it, which is the reference point for every freshness claim further down.
    """
    return ResponseMeta(
        request_id=request_id,
        correlation_id=correlation_id,
        contract_version=contract_version,
        generated_at=datetime.now(UTC),
        degraded_services=degraded_services or [],
    )
