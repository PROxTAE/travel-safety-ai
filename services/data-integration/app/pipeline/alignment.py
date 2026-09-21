"""Route ETA alignment for sourced weather and disaster evidence."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import cos, radians, sqrt

from app.domain.canonical import DisasterEvent, RouteSegment, TransportStatus, WeatherForecastPoint
from app.pipeline.corridor import EARTH_RADIUS_M, RouteSample, geodesic_distance_m
from app.pipeline.normalize import normalize_place

ALIGNMENT_VERSION = "1.0.0"


@dataclass(frozen=True)
class Alignment:
    source_id: str
    status: str
    distance_m: float
    route_eta: datetime
    evidence_time: datetime
    reason: str


@dataclass(frozen=True)
class TransportAlignment:
    status: str
    source_id: str
    reason: str


def align_transport(
    segment: RouteSegment, record: TransportStatus, *, time_tolerance_seconds: float
) -> TransportAlignment:
    """Require a linked trip, stops, service identity, and measured schedule time."""
    if time_tolerance_seconds < 0:
        raise ValueError("transport tolerance must be nonnegative")
    source_id = record.source.source_id
    if segment.transport_status_id != record.id or segment.mode != record.mode:
        return TransportAlignment("OUTSIDE_COVERAGE", source_id, "TRIP_OR_MODE_MISMATCH")
    if not all(
        (
            record.operator,
            record.service_number,
            segment.from_name,
            segment.to_name,
            segment.departure_time,
        )
    ):
        return TransportAlignment("UNAVAILABLE", source_id, "INSUFFICIENT_KEYS")
    if normalize_place(segment.from_name) != normalize_place(record.origin_stop.name) or (
        normalize_place(segment.to_name) != normalize_place(record.destination_stop.name)
    ):
        return TransportAlignment("OUTSIDE_COVERAGE", source_id, "STOP_MISMATCH")
    scheduled = record.estimated_departure or record.scheduled_departure
    if scheduled is None:
        return TransportAlignment("UNAVAILABLE", source_id, "SCHEDULE_MISSING")
    if abs((segment.departure_time - scheduled).total_seconds()) > time_tolerance_seconds:
        return TransportAlignment("OUTSIDE_COVERAGE", source_id, "TIME_MISMATCH")
    if record.quality.status in {"STALE", "UNAVAILABLE"}:
        return TransportAlignment(record.quality.status, source_id, "SOURCE_QUALITY")
    return TransportAlignment("MATCHED", source_id, "TRIP_STOP_TIME")


def _lon_delta(longitude: float, reference: float) -> float:
    return (longitude - reference + 180) % 360 - 180


def nearest_route_eta(
    samples: list[RouteSample], point: tuple[float, float]
) -> tuple[float, datetime]:
    """Project onto each short sampled segment and interpolate its ETA."""
    if len(samples) < 2:
        raise ValueError("route needs at least two samples")
    longitude, latitude = point
    latitude_radians = radians(latitude)
    best: tuple[float, datetime] | None = None
    for start, end in zip(samples, samples[1:], strict=False):
        ax = (
            radians(_lon_delta(start.longitude, longitude)) * cos(latitude_radians) * EARTH_RADIUS_M
        )
        ay = radians(start.latitude - latitude) * EARTH_RADIUS_M
        bx = radians(_lon_delta(end.longitude, longitude)) * cos(latitude_radians) * EARTH_RADIUS_M
        by = radians(end.latitude - latitude) * EARTH_RADIUS_M
        dx, dy = bx - ax, by - ay
        scale = dx * dx + dy * dy
        fraction = max(0.0, min(1.0, -(ax * dx + ay * dy) / scale)) if scale else 0.0
        distance = sqrt((ax + fraction * dx) ** 2 + (ay + fraction * dy) ** 2)
        eta = start.eta + timedelta(seconds=(end.eta - start.eta).total_seconds() * fraction)
        candidate = (distance, eta)
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    return best[0], best[1].astimezone(UTC)


def align_weather(
    samples: list[RouteSample],
    record: WeatherForecastPoint,
    *,
    radius_m: float,
    time_tolerance_seconds: float,
) -> Alignment:
    if radius_m < 0 or time_tolerance_seconds < 0:
        raise ValueError("weather tolerances must be nonnegative")
    distance, eta = nearest_route_eta(samples, record.location.coordinates)
    if distance > radius_m:
        status, reason = "OUTSIDE_COVERAGE", "DISTANCE"
    elif abs((record.valid_at - eta).total_seconds()) > time_tolerance_seconds:
        status, reason = "OUTSIDE_COVERAGE", "FORECAST_TIME"
    elif record.quality.status in {"STALE", "UNAVAILABLE"}:
        status, reason = record.quality.status, "SOURCE_QUALITY"
    else:
        status, reason = "MATCHED", "SPACE_TIME"
    return Alignment(
        record.source.source_id, status, distance, eta, record.valid_at.astimezone(UTC), reason
    )


def align_disaster(
    samples: list[RouteSample],
    record: DisasterEvent,
    *,
    radius_m: float,
) -> Alignment:
    if radius_m < 0:
        raise ValueError("disaster radius must be nonnegative")
    distance, eta = nearest_route_eta(samples, record.geometry.coordinates)
    if distance > radius_m:
        status, reason = "OUTSIDE_COVERAGE", "DISTANCE"
    elif eta < record.effective_at or (record.ends_at is not None and eta > record.ends_at):
        status, reason = "OUTSIDE_COVERAGE", "EVENT_WINDOW"
    elif record.quality.status in {"STALE", "UNAVAILABLE"}:
        status, reason = record.quality.status, "SOURCE_QUALITY"
    else:
        status, reason = "MATCHED", "SPACE_TIME"
    return Alignment(
        record.source.source_id, status, distance, eta, record.effective_at.astimezone(UTC), reason
    )


def weather_coverage(
    samples: list[RouteSample],
    records: list[WeatherForecastPoint],
    *,
    radius_m: float,
    time_tolerance_seconds: float,
) -> float:
    if not samples:
        raise ValueError("route samples required")
    if radius_m < 0 or time_tolerance_seconds < 0:
        raise ValueError("weather tolerances must be nonnegative")
    covered = sum(
        any(
            geodesic_distance_m((sample.longitude, sample.latitude), record.location.coordinates)
            <= radius_m
            and abs((record.valid_at - sample.eta).total_seconds()) <= time_tolerance_seconds
            and record.quality.status not in {"STALE", "UNAVAILABLE"}
            for record in records
        )
        for sample in samples
    )
    return covered / len(samples)
