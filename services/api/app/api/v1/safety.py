"""Safety events and map-oriented hazard queries.

Proxies canonical hazards from module 04 with bounding-box and layer filtering.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.responses import list_response
from app.api.v1.me import TravelPrincipal
from app.clients.external_data import ExternalDataClient, get_external_data_client
from app.errors.codes import FieldErrorCode
from app.errors.exceptions import FieldError, ValidationFailed
from app.observability.logging import get_logger
from app.schemas.envelope import ListResponse, PageMeta
from app.schemas.safety import SafetyEventModel, SafetyLayer

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/safety", tags=["safety"])


def _parse_and_validate_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """Parse `west,south,east,north` and assert standard geographic bounds."""
    try:
        parts = [float(p.strip()) for p in bbox_str.split(",")]
    except (ValueError, AttributeError):
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="bbox",
                    code=FieldErrorCode.INVALID_FORMAT,
                    message="Bounding box must be formatted as west,south,east,north coordinates.",
                )
            ]
        ) from None

    if len(parts) != 4:
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="bbox",
                    code=FieldErrorCode.INVALID_FORMAT,
                    message="Bounding box must contain exactly 4 values: west,south,east,north.",
                )
            ]
        )

    west, south, east, north = parts
    errors: list[FieldError] = []

    if not (-180.0 <= west <= 180.0):
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.OUT_OF_RANGE,
                message="west coordinate must be in [-180, 180].",
            )
        )
    if not (-180.0 <= east <= 180.0):
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.OUT_OF_RANGE,
                message="east coordinate must be in [-180, 180].",
            )
        )
    if not (-90.0 <= south <= 90.0):
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.OUT_OF_RANGE,
                message="south coordinate must be in [-90, 90].",
            )
        )
    if not (-90.0 <= north <= 90.0):
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.OUT_OF_RANGE,
                message="north coordinate must be in [-90, 90].",
            )
        )
    if south > north:
        errors.append(
            FieldError(
                path="bbox",
                code=FieldErrorCode.INCONSISTENT,
                message="south coordinate cannot be greater than north coordinate.",
            )
        )

    if errors:
        raise ValidationFailed(field_errors=errors)

    return west, south, east, north


@router.get(
    "/events",
    summary="Query safety events in viewport",
    response_model=ListResponse[SafetyEventModel],
    responses={
        200: {"description": "Hazards intersecting the viewport and instant."},
        400: {"description": "Validation error (invalid bbox coordinates)."},
        401: {"description": "Unauthorized."},
        503: {"description": "External data provider unavailable."},
    },
)
async def query_safety_events(
    request: Request,
    principal: TravelPrincipal,
    client: Annotated[ExternalDataClient, Depends(get_external_data_client)],
    bbox: Annotated[
        str,
        Query(
            description="`west,south,east,north` in degrees.",
            pattern=r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$",
        ),
    ],
    at: Annotated[
        datetime | None,
        Query(description="Instant to evaluate, defaulting to now."),
    ] = None,
    layers: Annotated[list[SafetyLayer] | None, Query(description="Layers to include.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ListResponse[SafetyEventModel]:
    """Fetch safety events for the map viewport."""
    parsed_bbox = _parse_and_validate_bbox(bbox)

    target_layers = (
        set(layers) if layers else {"WEATHER", "DISASTER", "TRANSPORT", "OFFICIAL_ALERT"}
    )

    events_raw, degraded = await client.disasters_query(
        bbox=parsed_bbox,
        start=at,
    )

    safety_events: list[SafetyEventModel] = []
    for item in events_raw:
        layer: SafetyLayer = "DISASTER"
        if layer not in target_layers:
            continue

        authority = item.get("source", {}).get("authority", "UNKNOWN")
        is_official = authority in ("OFFICIAL", "GOVERNMENT", "UN", "METEOROLOGICAL_AGENCY")

        valid_from = item.get("effective_at") or item.get("observed_at")
        valid_to = item.get("expires_at")

        safety_events.append(
            SafetyEventModel(
                event_id=item["event_id"],
                layer=layer,
                event_type=item["event_type"],
                title=item["title"],
                severity=item.get("severity", "UNKNOWN"),
                geometry=item["geometry"],
                official=is_official,
                valid_from=valid_from,
                valid_to=valid_to,
                detail_url=None,
                quality=item.get("quality", {}),
                source=item.get("source", {}),
            )
        )

    paged_events = safety_events[:limit]
    page = PageMeta(cursor=None, next_cursor=None, has_more=False)
    return list_response(request, paged_events, page=page, degraded_services=degraded)
