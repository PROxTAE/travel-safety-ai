"""Building the success envelope.

Handlers return their data; this assembles `meta` around it. Centralising it means no endpoint can
ship without a `request_id`, and `generated_at` is always the moment the API produced the answer —
the reference point every freshness claim downstream is measured against.
"""

from __future__ import annotations

from typing import TypeVar

from fastapi import Request

from app.middleware.request_context import current_correlation_id, current_request_id
from app.schemas.envelope import DataResponse, DegradedService, ListResponse, PageMeta, build_meta

DataT = TypeVar("DataT")


def data_response(
    request: Request,
    data: DataT,
    *,
    degraded_services: list[DegradedService] | None = None,
) -> DataResponse[DataT]:
    """Wrap one resource."""
    return DataResponse[DataT](
        data=data,
        meta=build_meta(
            request_id=current_request_id(),
            correlation_id=current_correlation_id(),
            contract_version=request.app.state.settings.contract_version,
            degraded_services=degraded_services,
        ),
    )


def list_response(
    request: Request,
    data: list[DataT],
    *,
    page: PageMeta | None = None,
    degraded_services: list[DegradedService] | None = None,
) -> ListResponse[DataT]:
    """Wrap a page of resources."""
    return ListResponse[DataT](
        data=data,
        meta=build_meta(
            request_id=current_request_id(),
            correlation_id=current_correlation_id(),
            contract_version=request.app.state.settings.contract_version,
            degraded_services=degraded_services,
        ),
        page=page or PageMeta(cursor=None, next_cursor=None, has_more=False),
    )
