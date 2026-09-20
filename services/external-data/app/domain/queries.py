"""Canonical query shapes shared by adapters of the same capability.

`DisasterQuery` started life inside the USGS adapter; it moved here when the
second disaster source arrived, so that every source answers the same question
rather than each defining its own dialect of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.enums import EventType, PlaceType, TravelMode


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


# Verified against the live API on 2026-09-20, not taken from memory: ORS
# rejects `alternative_routes` with more than two waypoints (error 2003,
# "incompatible with parameter '(number of waypoints > 2)'") and caps
# `target_count` at 3. Both fixtures live in
# tests/fixtures/real-sanitized/openrouteservice/.
MAX_ALTERNATIVE_ROUTES = 3
ALTERNATIVES_MAX_WAYPOINTS = 2


@dataclass(slots=True)
class RouteQuery:
    """A road route request.

    `waypoints` are (longitude, latitude) in GeoJSON order, start first. Two is
    the normal case; extra points are via-points the route must pass through.

    `avoid_polygons` is GeoJSON Polygon/MultiPolygon geometry the caller wants
    kept out of the route - module 06 hands these over for hazard areas. The
    provider enforces its own size limit on them and we surface that rejection
    as a typed error rather than guessing a threshold here, because the
    published limit depends on the plan.
    """

    waypoints: list[tuple[float, float]]
    mode: TravelMode = TravelMode.CAR
    alternatives: int = 0
    avoid_polygons: dict[str, object] | None = None
    # Prefer a shorter distance over a shorter time, or the reverse. Passed to
    # the provider as its `preference`; anything it does not know is refused at
    # the boundary rather than silently dropped.
    preference: str = "recommended"
    departure_at: datetime | None = None
    language: str = "en"

    def __post_init__(self) -> None:
        if len(self.waypoints) < 2:
            raise ValueError("a route needs at least an origin and a destination")
        for longitude, latitude in self.waypoints:
            if not -180.0 <= longitude <= 180.0:
                raise ValueError(f"longitude {longitude} out of range")
            if not -90.0 <= latitude <= 90.0:
                raise ValueError(f"latitude {latitude} out of range")


@dataclass(slots=True)
class NearbyPlacesQuery:
    """Emergency directory lookup around one coordinate."""

    longitude: float
    latitude: float
    radius_m: int = 2000
    place_types: list[PlaceType] = field(default_factory=list)
    limit: int = 20
    language: str = "en"

    def __post_init__(self) -> None:
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude {self.longitude} out of range")
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude {self.latitude} out of range")
