"""Canonical query shapes shared by adapters of the same capability.

`DisasterQuery` started life inside the USGS adapter; it moved here when the
second disaster source arrived, so that every source answers the same question
rather than each defining its own dialect of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.enums import EventType


@dataclass(slots=True)
class DisasterQuery:
    """Bounding box, time window and event types to look for.

    `bbox` is `(min_lon, min_lat, max_lon, max_lat)` in GeoJSON order and may
    cross the antimeridian, in which case `min_lon > max_lon` and the box is the
    union of two spans.
    """

    bbox: tuple[float, float, float, float] | None = None
    start: datetime | None = None
    end: datetime | None = None
    event_types: list[EventType] = field(default_factory=list)
    # Earthquake-specific; sources that publish other hazards ignore it.
    min_magnitude: float | None = None
