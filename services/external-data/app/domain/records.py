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
from app.domain.enums import Severity


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
