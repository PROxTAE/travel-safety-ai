"""Open-Meteo Forecast adapter.

Mapping verified against `tests/fixtures/real-sanitized/open_meteo_weather/`.
Three traps this adapter exists to absorb, each confirmed against a real
response rather than read off the documentation:

1. `hourly.time` has **no zone suffix** even when `timezone=UTC` is requested -
   the provider reports `timezone: "GMT"`, `utc_offset_seconds: 0` and returns
   `"2026-09-19T00:00"`. Parsing that as naive local time silently shifts every
   forecast by the host offset.
2. `hourly` is **column-oriented**: parallel arrays, not a list of objects. A
   ragged response is a schema change, not a partial result.
3. A batched request returns a **JSON array**, a single-coordinate request
   returns an **object** - and the array carries no id, so results map back to
   requests by position only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, ValidationError

from app.adapters.base import CoverageDecision, ProviderAdapter, ProviderRequest
from app.domain.canonical import DataQuality
from app.domain.enums import DataStatus, QualityFlag
from app.domain.errors import ProviderError, ProviderErrorCode
from app.domain.records import GeoPoint, WeatherForecastPoint
from app.transport.http import ProviderResponse

# One request carries at most this many points. The real ceiling is the
# provider's rate limit rather than a documented batch size, so this stays
# conservative until quota item C1 is verified against a live account.
MAX_SAMPLES_PER_REQUEST = 10

# Hourly forecast is FRESH for an hour (shared context § 10). The cache TTL is
# 900s, so a cache hit is always inside that window.
FRESH_WITHIN_SECONDS = 3600

HOURLY_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "precipitation_probability",
    "snowfall",
    "wind_speed_10m",
    "wind_gusts_10m",
    "visibility",
    "weather_code",
)

# Provider field -> canonical field. The units requested below make every one of
# these a straight copy; if a unit ever changes, this table is where it shows.
FIELD_MAP = {
    "temperature_2m": "temperature_c",
    "apparent_temperature": "apparent_temperature_c",
    "precipitation": "precipitation_mm",
    "precipitation_probability": "precipitation_probability",
    "snowfall": "snowfall_cm",
    "wind_speed_10m": "wind_speed_kmh",
    "wind_gusts_10m": "wind_gust_kmh",
    "visibility": "visibility_m",
    "weather_code": "weather_code",
}

EXPECTED_UNITS = {
    "temperature_2m": "°C",
    "apparent_temperature": "°C",
    "precipitation": "mm",
    "precipitation_probability": "%",
    "snowfall": "cm",
    "wind_speed_10m": "km/h",
    "wind_gusts_10m": "km/h",
    "visibility": "m",
}


@dataclass(slots=True)
class CoordinateSample:
    latitude: float
    longitude: float
    # When the traveller is expected at this point. Drives which forecast hour
    # is selected; without it the whole window is returned.
    eta: datetime | None = None
    sample_id: str | None = None


@dataclass(slots=True)
class WeatherQuery:
    samples: list[CoordinateSample] = field(default_factory=list)
    start: datetime | None = None
    end: datetime | None = None


class OpenMeteoHourly(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time: list[str]
    temperature_2m: list[float | None] = []
    apparent_temperature: list[float | None] = []
    precipitation: list[float | None] = []
    precipitation_probability: list[int | None] = []
    snowfall: list[float | None] = []
    wind_speed_10m: list[float | None] = []
    wind_gusts_10m: list[float | None] = []
    visibility: list[float | None] = []
    weather_code: list[int | None] = []


class OpenMeteoForecast(BaseModel):
    model_config = ConfigDict(extra="ignore")

    latitude: float
    longitude: float
    utc_offset_seconds: int
    timezone: str
    hourly: OpenMeteoHourly
    hourly_units: dict[str, str] = {}


class OpenMeteoWeatherAdapter(ProviderAdapter[WeatherQuery, WeatherForecastPoint]):
    def coverage(self, query: WeatherQuery) -> CoverageDecision:
        if not query.samples:
            return CoverageDecision(False, "no coordinate samples supplied")
        for sample in query.samples:
            if not -90.0 <= sample.latitude <= 90.0:
                return CoverageDecision(False, "latitude out of range")
            if not -180.0 <= sample.longitude <= 180.0:
                return CoverageDecision(False, "longitude out of range")
        if query.start and query.end and query.end < query.start:
            return CoverageDecision(False, "time window ends before it starts")
        return CoverageDecision(True)

    def build_request(self, query: WeatherQuery) -> ProviderRequest:
        selected = _select_samples(query.samples)
        params = {
            "latitude": ",".join(f"{s.latitude:.4f}" for s in selected),
            "longitude": ",".join(f"{s.longitude:.4f}" for s in selected),
            "hourly": ",".join(HOURLY_VARIABLES),
            "forecast_days": _forecast_days(query),
            # Always UTC with explicit units, so the adapter never has to guess
            # what it was handed.
            "timezone": "UTC",
            "timeformat": "iso8601",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }

        return ProviderRequest(
            path_or_url=self.provider.entry.endpoints["forecast"],
            params=params,
            cache_key_fields={
                # Bucket coordinates so two requests a few metres apart share a
                # cache entry - the provider snaps to a grid anyway.
                "points": [[round(s.latitude, 2), round(s.longitude, 2)] for s in selected],
                "hours": _window_bucket(query),
                # What gets cached is the *normalised* records, which ETA
                # selection has already narrowed to one hour per sample and
                # labelled with that caller's ids. Both therefore have to be
                # part of the key, or a later traveller with a different ETA
                # gets the first traveller's hour back under their own name.
                "etas": [
                    s.eta.astimezone(UTC).replace(minute=0, second=0, microsecond=0).isoformat()
                    if s.eta
                    else None
                    for s in selected
                ],
                "ids": [s.sample_id for s in selected],
                "fields": list(HOURLY_VARIABLES),
                "units": "c_kmh_mm",
            },
        )

    def validate(self, response: ProviderResponse) -> list[OpenMeteoForecast]:
        # Single coordinate -> object; batched -> array. Normalise to a list.
        payload = response.payload
        entries = payload if isinstance(payload, list) else [payload]

        try:
            forecasts = [OpenMeteoForecast.model_validate(entry) for entry in entries]
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=(
                    "forecast response did not match the expected shape: "
                    f"{exc.error_count()} errors"
                ),
            ) from exc

        for forecast in forecasts:
            if forecast.utc_offset_seconds != 0:
                # We asked for UTC. Anything else means the timestamps in this
                # payload do not mean what the rest of the pipeline assumes.
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                    self.provider_id,
                    message="provider ignored timezone=UTC",
                )
            _assert_rectangular(forecast, self.provider_id)

        return forecasts

    def normalize(
        self,
        model: list[OpenMeteoForecast],
        response: ProviderResponse,
        query: WeatherQuery,
    ) -> list[WeatherForecastPoint]:
        selected = _select_samples(query.samples)

        if len(model) != len(selected):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                self.provider_id,
                message=(
                    f"expected {len(selected)} forecast entries, got {len(model)}; "
                    "results map to requests by position only"
                ),
            )

        coverage = round(len(selected) / len(query.samples), 3)
        downsampled = len(selected) < len(query.samples)
        unit_drift = _unit_drift(model[0])

        points: list[WeatherForecastPoint] = []
        for sample, forecast in zip(selected, model, strict=True):
            times = [_parse_utc(value) for value in forecast.hourly.time]
            grid = GeoPoint.from_lat_lon(forecast.latitude, forecast.longitude)
            grid_offset_km = _haversine_km(
                sample.latitude, sample.longitude, forecast.latitude, forecast.longitude
            )

            for index in _indices_for(sample, query, times):
                eta_offset = (
                    int((times[index] - sample.eta).total_seconds()) if sample.eta else None
                )
                points.append(
                    WeatherForecastPoint(
                        id=f"{self.provider_id}:{forecast.latitude}:{forecast.longitude}"
                        f":{times[index].isoformat()}",
                        location=grid,
                        valid_at=times[index],
                        sample_id=sample.sample_id,
                        eta_offset_seconds=eta_offset,
                        quality=_quality(
                            grid_offset_km=grid_offset_km,
                            coverage=coverage,
                            downsampled=downsampled,
                            eta_offset_seconds=eta_offset,
                            unit_drift=unit_drift,
                        ),
                        source=self.provenance(
                            response,
                            provider_record_id=(
                                f"{forecast.latitude},{forecast.longitude}"
                                f"@{times[index].isoformat()}"
                            ),
                            # Model output, not an observation. The contract is
                            # explicit that fetched_at must not stand in here.
                            observed_at=None,
                            payload_for_hash={
                                "lat": forecast.latitude,
                                "lon": forecast.longitude,
                                "t": times[index].isoformat(),
                                "v": _row(forecast, index),
                            },
                        ),
                        **_measurements(forecast, index),
                    )
                )

        return points

    def _dehydrate(self, records: list[WeatherForecastPoint]) -> list[dict[str, object]]:
        return [record.model_dump(mode="json") for record in records]

    def _rehydrate(self, payload: object) -> list[WeatherForecastPoint]:
        assert isinstance(payload, list)
        return [WeatherForecastPoint.model_validate(item) for item in payload]


# --------------------------------------------------------------------- helpers


def _select_samples(samples: list[CoordinateSample]) -> list[CoordinateSample]:
    """Cap the request at the provider budget.

    Evenly spaced rather than truncated: a route sampled at its first ten points
    reports nothing about its second half, which is exactly the half a traveller
    has not driven yet.
    """
    if len(samples) <= MAX_SAMPLES_PER_REQUEST:
        return list(samples)
    step = (len(samples) - 1) / (MAX_SAMPLES_PER_REQUEST - 1)
    picked = [samples[round(index * step)] for index in range(MAX_SAMPLES_PER_REQUEST)]
    return picked


def _parse_utc(value: str) -> datetime:
    """Open-Meteo returns `2026-09-19T00:00` with no suffix even under
    `timezone=UTC`. `validate()` has already asserted the offset is zero."""
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _forecast_days(query: WeatherQuery) -> int:
    if query.end is None:
        return 2
    span = query.end - (query.start or datetime.now(UTC))
    return max(1, min(16, span.days + 2))


def _window_bucket(query: WeatherQuery) -> str:
    start = query.start.replace(minute=0, second=0, microsecond=0) if query.start else None
    end = query.end.replace(minute=0, second=0, microsecond=0) if query.end else None
    return f"{start.isoformat() if start else '*'}/{end.isoformat() if end else '*'}"


def _assert_rectangular(forecast: OpenMeteoForecast, provider_id: str) -> None:
    expected = len(forecast.hourly.time)
    for name in HOURLY_VARIABLES:
        column = getattr(forecast.hourly, name)
        if column and len(column) != expected:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_SCHEMA_CHANGED,
                provider_id,
                message=f"hourly.{name} has {len(column)} values for {expected} timestamps",
            )


def _unit_drift(forecast: OpenMeteoForecast) -> list[str]:
    """We request explicit units, so a mismatch means the provider changed
    behaviour. Recorded rather than raised: the values are still usable, and a
    silent unit change is exactly what the canary needs to surface."""
    return [
        f"{name}: expected {expected}, got {forecast.hourly_units[name]}"
        for name, expected in EXPECTED_UNITS.items()
        if name in forecast.hourly_units and forecast.hourly_units[name] != expected
    ]


def _row(forecast: OpenMeteoForecast, index: int) -> dict[str, float | int | None]:
    row: dict[str, float | int | None] = {}
    for name in HOURLY_VARIABLES:
        column = getattr(forecast.hourly, name)
        row[name] = column[index] if index < len(column) else None
    return row


def _measurements(forecast: OpenMeteoForecast, index: int) -> dict[str, object]:
    return {
        canonical: getattr(forecast.hourly, provider_field)[index]
        if index < len(getattr(forecast.hourly, provider_field))
        else None
        for provider_field, canonical in FIELD_MAP.items()
    }


def _indices_for(sample: CoordinateSample, query: WeatherQuery, times: list[datetime]) -> list[int]:
    if not times:
        return []

    eta = sample.eta
    if eta is not None:
        # One point per sample: the hour closest to when the traveller arrives.
        nearest = min(range(len(times)), key=lambda i: abs(times[i] - eta))
        return [nearest]

    start = query.start
    end = query.end
    if start is None and end is None:
        return list(range(len(times)))

    return [
        index
        for index, moment in enumerate(times)
        if (start is None or moment >= start) and (end is None or moment <= end)
    ]


def _quality(
    *,
    grid_offset_km: float,
    coverage: float,
    downsampled: bool,
    eta_offset_seconds: int | None,
    unit_drift: list[str],
) -> DataQuality:
    flags = [QualityFlag.MISSING]  # no observation time: this is model output
    notes = ["forecast is model output; the provider supplies no observation time"]

    if grid_offset_km > 0.0:
        notes.append(
            f"returned coordinate is the model grid cell, {grid_offset_km:.1f} km "
            "from the requested point"
        )
    if grid_offset_km > 25.0:
        flags.append(QualityFlag.INFERRED)

    if downsampled:
        flags.append(QualityFlag.INCOMPLETE)
        notes.append(
            f"route was downsampled to {MAX_SAMPLES_PER_REQUEST} points to stay "
            "inside the provider budget"
        )

    if eta_offset_seconds is not None and abs(eta_offset_seconds) > 1800:
        flags.append(QualityFlag.INFERRED)
        notes.append(
            f"nearest forecast hour is {abs(eta_offset_seconds) // 60} minutes from "
            "the supplied ETA"
        )

    if unit_drift:
        flags.append(QualityFlag.CONFLICTING)
        notes.extend(unit_drift)

    return DataQuality(
        status=DataStatus.FRESH,
        flags=flags,
        coverage=coverage,
        freshness_seconds=0,
        notes=notes,
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    radius_km = 6371.0088
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * radius_km * asin(sqrt(a))


def default_window(hours: int = 24) -> tuple[datetime, datetime]:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return now, now + timedelta(hours=hours)
