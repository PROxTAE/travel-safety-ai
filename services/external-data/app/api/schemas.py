"""Request bodies for the internal endpoints.

Validation is strict at the boundary (`extra="forbid"`): a caller sending an
unexpected field is told, rather than having it silently dropped and wondering
why the filter did nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import EventType, PlaceType, ProviderKind, TravelMode

MAX_SAMPLES = 200
# Mirrors the provider limits verified in app/domain/queries.py; repeated here
# so an impossible request is refused at the boundary with a field error rather
# than travelling all the way to a provider 400.
MAX_ALTERNATIVES = 3
MAX_PLACE_RADIUS_M = 10_000
# Every capability a combined context request may ask for. FLIGHT is absent on
# purpose: the shared context forbids serving Amadeus test data as a real
# result, so module 04 will never answer it, and offering it here would invite a
# caller to build a screen around an answer that never arrives.
CONTEXT_CAPABILITIES = (
    ProviderKind.WEATHER,
    ProviderKind.DISASTER,
    ProviderKind.ROUTE,
    ProviderKind.TRANSIT,
    ProviderKind.EMERGENCY_DIRECTORY,
)


class GeocodeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    count: int = Field(default=5, ge=1, le=20)
    language: str = Field(default="en", min_length=2, max_length=5)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)


class CoordinateSampleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    # When the traveller is expected here. Present -> one forecast point at the
    # nearest hour; absent -> every hour inside the window.
    eta: datetime | None = None
    sample_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _eta_is_aware(self) -> Self:
        if self.eta is not None and self.eta.tzinfo is None:
            raise ValueError("eta must carry a timezone offset")
        return self


class WeatherQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: list[CoordinateSampleIn] = Field(min_length=1, max_length=MAX_SAMPLES)
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def _window_is_sane(self) -> Self:
        for name in ("start", "end"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must carry a timezone offset")
        if self.start and self.end and self.end < self.start:
            raise ValueError("end must not precede start")
        return self


class DisasterQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # GeoJSON order: min_lon, min_lat, max_lon, max_lat. Omit for a global query.
    bbox: tuple[float, float, float, float] | None = None
    start: datetime | None = None
    end: datetime | None = None
    # Typed at the boundary: an unknown hazard name is a caller mistake and
    # must come back as VALIDATION_ERROR, not as a 500 from deep inside.
    event_types: list[EventType] = Field(default_factory=list)
    min_magnitude: float | None = Field(default=None, ge=0.0, le=10.0)

    @model_validator(mode="after")
    def _window_and_bbox_are_sane(self) -> Self:
        for name in ("start", "end"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must carry a timezone offset")
        if self.start and self.end and self.end < self.start:
            raise ValueError("end must not precede start")
        if self.bbox is not None:
            min_lon, min_lat, max_lon, max_lat = self.bbox
            if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
                raise ValueError("bbox longitude out of range")
            if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
                raise ValueError("bbox latitude out of range")
            if min_lat > max_lat:
                raise ValueError("bbox latitudes are inverted")
        return self


class RouteQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # GeoJSON order, origin first: [[lon, lat], ...]. Via points are allowed,
    # but the provider will not return alternatives alongside them.
    waypoints: list[tuple[float, float]] = Field(min_length=2, max_length=50)
    mode: TravelMode = TravelMode.CAR
    alternatives: int = Field(default=0, ge=0, le=MAX_ALTERNATIVES)
    # GeoJSON Polygon or MultiPolygon the route must stay out of. Module 06
    # sends hazard areas here.
    avoid_polygons: dict[str, object] | None = None
    preference: str = Field(default="recommended", max_length=32)
    departure_at: datetime | None = None
    language: str = Field(default="en", min_length=2, max_length=5)

    @model_validator(mode="after")
    def _coordinates_are_sane(self) -> Self:
        for longitude, latitude in self.waypoints:
            if not -180.0 <= longitude <= 180.0:
                raise ValueError("waypoint longitude out of range")
            if not -90.0 <= latitude <= 90.0:
                # Almost always lon/lat written the wrong way round.
                raise ValueError("waypoint latitude out of range")
        if self.departure_at is not None and self.departure_at.tzinfo is None:
            raise ValueError("departure_at must carry a timezone offset")
        if self.avoid_polygons is not None:
            geometry_type = self.avoid_polygons.get("type")
            if geometry_type not in ("Polygon", "MultiPolygon"):
                raise ValueError("avoid_polygons must be a GeoJSON Polygon or MultiPolygon")
        return self


class NearbyPlacesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    longitude: float = Field(ge=-180.0, le=180.0)
    latitude: float = Field(ge=-90.0, le=90.0)
    radius_m: int = Field(default=2000, ge=1, le=MAX_PLACE_RADIUS_M)
    # Typed at the boundary for the same reason as event_types: an unknown
    # category is the caller's mistake and should say so.
    place_types: list[PlaceType] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=100)
    language: str = Field(default="en", min_length=2, max_length=5)


class ContextQueryRequest(BaseModel):
    """One question about a journey, answered by every capability that applies.

    Nothing here is required on its own; what is present decides what gets
    asked. Sending nothing at all is a mistake rather than a global query, so
    it is refused - a request that accidentally asks for everything everywhere
    is expensive against free-tier quota and almost never what was meant.
    """

    model_config = ConfigDict(extra="forbid")

    # Points along the journey, each with the time the traveller is expected
    # there. Drives weather, and gives the other capabilities somewhere to look.
    samples: list[CoordinateSampleIn] = Field(default_factory=list, max_length=MAX_SAMPLES)
    # Origin first, GeoJSON order. Present -> routes are requested too.
    waypoints: list[tuple[float, float]] | None = Field(default=None, max_length=50)
    # Where to look for hazards. Absent -> whatever window feed the sources
    # publish, filtered by the times below.
    bbox: tuple[float, float, float, float] | None = None
    start: datetime | None = None
    end: datetime | None = None

    mode: TravelMode = TravelMode.CAR
    alternatives: int = Field(default=0, ge=0, le=MAX_ALTERNATIVES)
    avoid_polygons: dict[str, object] | None = None
    event_types: list[EventType] = Field(default_factory=list)
    place_types: list[PlaceType] = Field(default_factory=list)
    places_radius_m: int = Field(default=2000, ge=1, le=MAX_PLACE_RADIUS_M)
    # Where to look for hospitals and police. Absent -> the destination, which
    # is where a traveller most often needs them.
    places_near: CoordinateSampleIn | None = None

    # Empty -> infer from what was sent. Naming one explicitly also serves as
    # "ask this even though nothing implied it".
    include: list[ProviderKind] = Field(default_factory=list)

    language: str = Field(default="en", min_length=2, max_length=5)
    # The whole request, not each provider. A capability that overruns is
    # cancelled and reported; the rest of the answer still comes back.
    deadline_seconds: float = Field(default=25.0, ge=1.0, le=60.0)

    @model_validator(mode="after")
    def _has_something_to_go_on(self) -> Self:
        if not self.samples and not self.waypoints and not self.bbox:
            raise ValueError(
                "send at least one of samples, waypoints or bbox - "
                "an empty context query would ask every provider about everywhere"
            )
        for name in ("start", "end"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must carry a timezone offset")
        if self.start and self.end and self.end < self.start:
            raise ValueError("end must not precede start")

        if self.waypoints is not None:
            if len(self.waypoints) < 2:
                raise ValueError("a route needs at least an origin and a destination")
            for longitude, latitude in self.waypoints:
                if not -180.0 <= longitude <= 180.0:
                    raise ValueError("waypoint longitude out of range")
                if not -90.0 <= latitude <= 90.0:
                    # Almost always lon/lat written the wrong way round.
                    raise ValueError("waypoint latitude out of range")

        if self.bbox is not None:
            min_lon, min_lat, max_lon, max_lat = self.bbox
            if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
                raise ValueError("bbox longitude out of range")
            if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
                raise ValueError("bbox latitude out of range")

        unsupported = [kind for kind in self.include if kind not in CONTEXT_CAPABILITIES]
        if unsupported:
            names = ", ".join(str(kind) for kind in unsupported)
            raise ValueError(
                f"module 04 has no adapter for: {names}; "
                f"this endpoint answers {', '.join(str(k) for k in CONTEXT_CAPABILITIES)}"
            )

        if self.avoid_polygons is not None:
            if self.avoid_polygons.get("type") not in ("Polygon", "MultiPolygon"):
                raise ValueError("avoid_polygons must be a GeoJSON Polygon or MultiPolygon")
        return self


class TransitQueryRequest(BaseModel):
    """Live transit status. Coverage is per agency and never global."""

    model_config = ConfigDict(extra="forbid")

    # GeoJSON order: min_lon, min_lat, max_lon, max_lat. Picks which registered
    # feeds can answer; a box outside all of them is UNSUPPORTED_COVERAGE, not
    # an empty list.
    bbox: tuple[float, float, float, float] | None = None
    route_ids: list[str] = Field(default_factory=list, max_length=50)
    stop_ids: list[str] = Field(default_factory=list, max_length=50)
    feed_ids: list[str] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def _bbox_is_sane(self) -> Self:
        if self.bbox is not None:
            min_lon, min_lat, max_lon, max_lat = self.bbox
            if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
                raise ValueError("bbox longitude out of range")
            if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
                raise ValueError("bbox latitude out of range")
        return self
