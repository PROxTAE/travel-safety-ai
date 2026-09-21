"""Canonical records emitted by module 04.

Shapes follow 00_API_AND_DATA_CONTRACTS.md § 3. `LocationRef` is reproduced
field-for-field from § 3.1, so provenance and quality ride alongside it in
`GeocodeResult` rather than being bolted onto the contract shape.
`WeatherForecastPoint` (§ 3.5) carries `quality` and `source` directly, because
the contract puts them there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.canonical import DataQuality, SourceProvenance
from app.domain.enums import (
    EventType,
    PlaceType,
    RiskLevel,
    RouteLabel,
    Severity,
    TransportStatusCode,
    TravelMode,
)


class GeoPoint(BaseModel):
    """GeoJSON Point, RFC 7946: coordinates are [longitude, latitude]."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @model_validator(mode="after")
    def _within_range(self) -> Self:
        longitude, latitude = self.coordinates
        if not -180.0 <= longitude <= 180.0:
            raise ValueError(f"longitude {longitude} out of range")
        if not -90.0 <= latitude <= 90.0:
            # Catches the classic reversed-coordinate bug: a latitude above 90
            # almost always means lon/lat were swapped.
            raise ValueError(f"latitude {latitude} out of range")
        return self

    @classmethod
    def from_lat_lon(cls, latitude: float, longitude: float) -> GeoPoint:
        return cls(coordinates=(longitude, latitude))

    @property
    def latitude(self) -> float:
        return self.coordinates[1]

    @property
    def longitude(self) -> float:
        return self.coordinates[0]


class LocationRef(BaseModel):
    """Contract § 3.1, reproduced exactly."""

    model_config = ConfigDict(extra="forbid")

    place_id: str
    display_name: str
    coordinates: GeoPoint
    country_code: str | None = None
    admin1: str | None = None
    timezone: str | None = None
    provider: str
    # Module 04 never sets this true: confirmation is a user action owned by
    # modules 01/02.
    confirmed_by_user: bool = False

    @model_validator(mode="after")
    def _country_code_shape(self) -> Self:
        if self.country_code is not None:
            code = self.country_code.upper()
            if len(code) != 2 or not code.isalpha():
                raise ValueError("country_code must be ISO-3166-1 alpha-2")
            object.__setattr__(self, "country_code", code)
        return self


class GeocodeResult(BaseModel):
    """A LocationRef with the provenance and quality every module-04 record carries."""

    model_config = ConfigDict(extra="forbid")

    location: LocationRef
    quality: DataQuality
    source: SourceProvenance


class WeatherForecastPoint(BaseModel):
    """Contract § 3.5.

    Every measurement is nullable on purpose. A value the provider does not
    supply is `null` plus a quality flag - never `0`, which would read as
    "no rain" rather than "unknown".
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    location: GeoPoint
    valid_at: datetime

    temperature_c: float | None = None
    apparent_temperature_c: float | None = None
    precipitation_mm: float | None = None
    precipitation_probability: int | None = Field(default=None, ge=0, le=100)
    snowfall_cm: float | None = None
    wind_speed_kmh: float | None = None
    wind_gust_kmh: float | None = None
    visibility_m: float | None = None
    weather_code: int | None = None

    # Left UNKNOWN until Q2/Q3 are answered by modules 05/06. The contract
    # requires the field; inventing a mapping here would be a silent decision
    # about what counts as dangerous weather.
    severity: Severity = Severity.UNKNOWN

    quality: DataQuality
    source: SourceProvenance

    # Set when the caller supplied an ETA: how far the chosen forecast hour sits
    # from the time the traveller is actually expected at this point.
    eta_offset_seconds: int | None = None
    sample_id: str | None = None


class DisasterEvent(BaseModel):
    """Contract § 3.7.

    The optional measurement fields below are an extension, agreed in
    `docs/canonical-field-mapping.md`: until Q2/Q3 are answered, `severity`
    stays UNKNOWN and the provider's own numbers are carried through in typed
    fields so modules 05/06 can decide what they mean. Discarding them and
    emitting only UNKNOWN would throw away the evidence the decision needs.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: EventType
    title: str
    description: str | None = None
    severity: Severity = Severity.UNKNOWN
    geometry: GeoPoint
    effective_at: datetime
    ends_at: datetime | None = None
    instruction: str | None = None
    official: bool
    quality: DataQuality
    source: SourceProvenance

    # --- provider measurements, carried through rather than interpreted ---
    magnitude: float | None = None
    magnitude_unit: str | None = None
    depth_km: float | None = None
    # PAGER green/yellow/orange/red, GDACS Green/Orange/Red - an impact alert
    # scale, deliberately NOT cast to Severity (open question Q3).
    alert_level: str | None = None
    tsunami: bool | None = None
    # Identifiers **of this event** in other networks - a USGS cross-network id,
    # a GLIDE number. Module 05 matches on these, so anything in here that does
    # not identify one specific event will make it merge unrelated hazards.
    cross_reference_ids: list[str] = Field(default_factory=list)
    # Who reported it, which is a different question from which event it is.
    # A network name is shared by every event that network publishes.
    reporting_networks: list[str] = Field(default_factory=list)
    # One provider event can have many episodes (a storm's successive updates).
    episode_id: str | None = None


class GeoLineString(BaseModel):
    """GeoJSON LineString, RFC 7946. Every position is [longitude, latitude].

    Route geometry is handed to module 05 for corridor intersection and to
    module 01 for drawing. A swapped pair puts the route in the wrong
    hemisphere, and unlike a single point nobody notices until the map is open,
    so the ordering is enforced here rather than trusted.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]] = Field(min_length=2)

    @model_validator(mode="after")
    def _within_range(self) -> Self:
        for index, (longitude, latitude) in enumerate(self.coordinates):
            if not -180.0 <= longitude <= 180.0:
                raise ValueError(f"longitude {longitude} out of range at index {index}")
            if not -90.0 <= latitude <= 90.0:
                raise ValueError(f"latitude {latitude} out of range at index {index}")
        return self


class RouteStep(BaseModel):
    """One manoeuvre. `instruction` is provider prose in the provider's own
    language; module 04 neither translates nor rewrites it."""

    model_config = ConfigDict(extra="forbid")

    distance_m: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    instruction: str | None = None
    street_name: str | None = None
    # Index range into the parent route geometry, so a consumer can highlight
    # the stretch of road a step refers to without re-matching coordinates.
    way_points: tuple[int, int] | None = None


class RouteSegment(BaseModel):
    """Contract § 3.8 `segments[]`.

    A road route from one provider is a single-mode segment. The field exists
    for multimodal itineraries, which module 04 does not build - it returns the
    road leg, and module 05 stitches legs together.
    """

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    mode: TravelMode
    from_name: str | None = None
    to_name: str | None = None
    geometry: GeoLineString | None = None
    distance_m: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    departure_time: datetime | None = None
    arrival_time: datetime | None = None
    transport_status_id: str | None = None
    steps: list[RouteStep] = Field(default_factory=list)


class RouteCandidate(BaseModel):
    """Contract § 3.8, as far as a routing provider can fill it.

    Two required contract fields are deliberately left unset here:

    `exposure` needs the route intersected with hazards and weather windows,
    which is module 05/06 work. `risk_level` is a judgement on top of that, and
    § 2 is explicit that risk must not be read as an action. A routing engine
    knows road geometry and travel time; it has no view on danger. Emitting
    `exposure.score = 0` and `closed = false` would be the most dangerous thing
    this module could do - a route across a closed bridge would arrive at
    module 07 asserting, in the contract's own vocabulary, that nothing is wrong.

    So both stay null/UNKNOWN and the record carries INCOMPLETE. The contract
    marks `exposure` required, which a raw producer cannot satisfy; that
    mismatch is raised for the Lead rather than papered over.
    """

    model_config = ConfigDict(extra="forbid")

    route_id: str
    provider_route_id: str | None = None
    label: RouteLabel
    mode: TravelMode
    geometry: GeoLineString
    segments: list[RouteSegment] = Field(default_factory=list)
    distance_m: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    transfers: int = Field(default=0, ge=0)

    # Filled by `/routes/evaluate` downstream, not here. See the class docstring.
    exposure: None = None
    risk_level: RiskLevel = RiskLevel.UNKNOWN

    quality: DataQuality
    # Plural here and singular on every other record, which is deliberate: a
    # route survives being stitched. Module 05 joins legs from several providers
    # into one itinerary and each leg's provenance has to survive that join. A
    # raw route from one provider carries a single-element list.
    sources: list[SourceProvenance] = Field(default_factory=list)

    # Bounding box of the whole geometry, in GeoJSON order
    # [min_lon, min_lat, max_lon, max_lat]. Module 05 uses it to pre-filter
    # hazards before doing the expensive corridor intersection.
    bbox: tuple[float, float, float, float] | None = None


class EmergencyPlace(BaseModel):
    """A police station / hospital / embassy resolved near a coordinate.

    The shared context is blunt about this data: OSM tags are "frequently stale
    or missing" and embassies "especially unreliable", and it must never stand
    in for an official phone directory. So `name` is nullable, `phone` is
    whatever OSM happened to hold, and every record carries quality alongside -
    a consumer that renders these must show the caveat, not just the pin.
    """

    model_config = ConfigDict(extra="forbid")

    # Named to match `emergency-poi.schema.json`. Note this is *not* the same
    # field as `LocationRef.place_id`, which the contract still calls place_id:
    # one identifies a geocoded place, the other a point of interest.
    poi_id: str
    poi_type: PlaceType
    # Required by the contract and nullable on purpose. Two of nineteen real
    # hospitals near Victory Monument carry no name tag in OpenStreetMap, one of
    # them 335 m away - closer than several that do. A non-nullable name leaves
    # only two options and both are wrong: drop the record and hide the nearest
    # hospital from someone who needs it, or invent a label the provider never
    # said.
    name: str | None = None
    location: GeoPoint
    # Straight-line metres from the query point as reported by the provider -
    # not travel distance, and explicitly not a promise that the road exists.
    distance_m: float | None = Field(default=None, ge=0)
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    opening_hours: str | None = None
    # The provider's own category string, kept so an OTHER mapping can be
    # diagnosed without re-fetching.
    provider_category: str | None = None
    quality: DataQuality
    source: SourceProvenance


class StopRef(BaseModel):
    """Contract § 3.6 `origin_stop` / `destination_stop`."""

    model_config = ConfigDict(extra="forbid")

    stop_id: str | None = None
    name: str
    coordinates: GeoPoint | None = None


class Cancellation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cancelled: bool
    reason: str | None = None
    announced_at: datetime | None = None


class TransportStatus(BaseModel):
    """Contract § 3.6 — live status for one scheduled trip.

    The invariant § 3.6 states outright: `ON_TIME` requires real-time evidence
    and must never be concluded from the absence of an alert. A running train
    whose scheduled trip cannot be matched is `UNKNOWN`, because without the
    schedule there is nothing to be on time against, and `delay_minutes` stays
    null rather than becoming a comforting zero.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    mode: TravelMode
    operator: str | None = None
    service_number: str | None = None
    origin_stop: StopRef
    destination_stop: StopRef

    scheduled_departure: datetime | None = None
    estimated_departure: datetime | None = None
    scheduled_arrival: datetime | None = None
    estimated_arrival: datetime | None = None

    status: TransportStatusCode = TransportStatusCode.UNKNOWN
    delay_minutes: int | None = None
    cancellation: Cancellation | None = None

    quality: DataQuality
    source: SourceProvenance

    # Which registered feed answered. Coverage is per agency and never global,
    # so a consumer needs to know whose data this is without parsing the id.
    feed_id: str | None = None

    @model_validator(mode="after")
    def _on_time_needs_a_schedule_to_be_on_time_against(self) -> Self:
        if self.status is TransportStatusCode.ON_TIME and self.delay_minutes is None:
            raise ValueError(
                "ON_TIME requires a measured delay; without a matched schedule "
                "the status is UNKNOWN (contract § 3.6)"
            )
        return self
