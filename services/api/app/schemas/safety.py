"""Safety event and map query models.

Mirrors `safety-event.schema.json` and the safety query operations in `public-api.yaml`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.envelope import PageMeta, ResponseMeta

SafetyLayer = Literal["WEATHER", "DISASTER", "TRANSPORT", "OFFICIAL_ALERT"]
DisasterEventType = Literal[
    "EARTHQUAKE",
    "CYCLONE",
    "STORM",
    "FLOOD",
    "WILDFIRE",
    "VOLCANO",
    "LANDSLIDE",
    "EXTREME_TEMPERATURE",
    "HEALTH",
    "TRANSPORT_CLOSURE",
    "OTHER",
]
Severity = Literal["INFO", "MINOR", "MODERATE", "SEVERE", "EXTREME", "UNKNOWN"]


class SafetyEventModel(BaseModel):
    """Map-sized summary of one hazard for the safety map."""

    model_config = ConfigDict(frozen=True)

    event_id: Annotated[str, Field(min_length=1, max_length=256)]
    layer: SafetyLayer
    event_type: DisasterEventType
    title: Annotated[str, Field(max_length=512)]
    severity: Severity
    geometry: dict[str, Any]
    official: bool
    valid_from: datetime | None
    valid_to: datetime | None
    detail_url: Annotated[str | None, Field(max_length=512)] = None
    quality: dict[str, Any]
    source: dict[str, Any]


class SafetyEventListResponse(BaseModel):
    """List of hazards intersecting the viewport and instant."""

    model_config = ConfigDict(frozen=True)

    data: list[SafetyEventModel]
    meta: ResponseMeta
    page: PageMeta
