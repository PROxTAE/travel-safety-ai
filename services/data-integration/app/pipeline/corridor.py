"""Geodesic route samples and dateline-safe corridor input geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import acos, asin, atan2, ceil, cos, degrees, radians, sin, sqrt

from app.domain.canonical import GeoLineString

EARTH_RADIUS_M = 6_371_008.8
CORRIDOR_VERSION = "1.0.0"


@dataclass(frozen=True)
class RouteSample:
    longitude: float
    latitude: float
    distance_m: float
    eta: datetime


def geodesic_distance_m(start: tuple[float, float], end: tuple[float, float]) -> float:
    lon1, lat1 = start
    lon2, lat2 = end
    dlat = radians(lat2 - lat1)
    dlon = radians((lon2 - lon1 + 180) % 360 - 180)
    value = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(min(1.0, sqrt(value)))


def _interpolate(
    start: tuple[float, float], end: tuple[float, float], fraction: float
) -> tuple[float, float]:
    if fraction == 0:
        return start
    if fraction == 1:
        return end
    lon1, lat1 = map(radians, start)
    lon2, lat2 = map(radians, end)
    x1, y1, z1 = cos(lat1) * cos(lon1), cos(lat1) * sin(lon1), sin(lat1)
    x2, y2, z2 = cos(lat2) * cos(lon2), cos(lat2) * sin(lon2), sin(lat2)
    dot = max(-1.0, min(1.0, x1 * x2 + y1 * y2 + z1 * z2))
    angle = acos(dot)
    if abs(sin(angle)) < 1e-12:
        if dot > 0:
            return start
        raise ValueError("antipodal or ambiguous route segment")
    weight1 = sin((1 - fraction) * angle) / sin(angle)
    weight2 = sin(fraction * angle) / sin(angle)
    x, y, z = weight1 * x1 + weight2 * x2, weight1 * y1 + weight2 * y2, weight1 * z1 + weight2 * z2
    longitude = (degrees(atan2(y, x)) + 180) % 360 - 180
    latitude = degrees(atan2(z, sqrt(x * x + y * y)))
    return longitude, latitude


def sample_route(
    line: GeoLineString,
    *,
    departure_at: datetime,
    duration_seconds: float,
    max_spacing_m: float,
) -> list[RouteSample]:
    if departure_at.utcoffset() is None:
        raise ValueError("departure time must have timezone")
    if duration_seconds < 0 or max_spacing_m <= 0:
        raise ValueError("duration and spacing must be nonnegative, with positive spacing")
    vertices = line.coordinates
    lengths = [
        geodesic_distance_m(vertices[index], vertices[index + 1])
        for index in range(len(vertices) - 1)
    ]
    total = sum(lengths)
    if total <= 0:
        raise ValueError("route has no measurable length")
    samples: list[RouteSample] = []
    walked = 0.0
    for index, length in enumerate(lengths):
        steps = max(1, ceil(length / max_spacing_m))
        for step in range(steps + 1):
            if index > 0 and step == 0:
                continue
            fraction = step / steps
            lon, lat = _interpolate(vertices[index], vertices[index + 1], fraction)
            distance = walked + fraction * length
            eta = departure_at + timedelta(seconds=duration_seconds * distance / total)
            samples.append(RouteSample(lon, lat, distance, eta.astimezone(UTC)))
        walked += length
    return samples


def split_dateline(samples: list[RouteSample]) -> list[list[list[float]]]:
    """Split a sampled line where longitude wraps to keep planar segments short."""
    if len(samples) < 2:
        raise ValueError("corridor needs at least two samples")
    parts: list[list[list[float]]] = [[[samples[0].longitude, samples[0].latitude]]]
    for previous, current in zip(samples, samples[1:], strict=False):
        delta = current.longitude - previous.longitude
        if abs(delta) <= 180:
            parts[-1].append([current.longitude, current.latitude])
            continue
        wrapped = delta - 360 if delta > 180 else delta + 360
        boundary = -180.0 if wrapped < 0 else 180.0
        opposite = -boundary
        fraction = (boundary - previous.longitude) / wrapped
        latitude = previous.latitude + fraction * (current.latitude - previous.latitude)
        parts[-1].append([boundary, latitude])
        parts.append([[opposite, latitude], [current.longitude, current.latitude]])
    return parts
