"""Request bodies for the Phase 2 internal endpoints.

Validation is strict at the boundary (`extra="forbid"`): a caller sending an
unexpected field is told, rather than having it silently dropped and wondering
why the filter did nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import EventType

MAX_SAMPLES = 200


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
