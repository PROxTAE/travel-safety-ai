"""Point-in-area and point-to-edge tests for Polygon and MultiPolygon hazards."""

from math import cos, radians, sqrt

from app.domain.canonical import GeoMultiPolygon, GeoPolygon
from app.pipeline.corridor import EARTH_RADIUS_M

Ring = list[tuple[float, float]]
Area = GeoPolygon | GeoMultiPolygon


def _shift(longitude: float, reference: float) -> float:
    return (longitude - reference + 180) % 360 - 180


def _inside(point: tuple[float, float], ring: Ring) -> bool:
    """Even-odd test with longitudes unwrapped around the point for dateline rings."""
    x, y = point
    shifted = [(_shift(lon, x), lat) for lon, lat in ring]
    inside = False
    for (x1, y1), (x2, y2) in zip(shifted, shifted[1:], strict=False):
        if (y1 > y) != (y2 > y) and 0 < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _polygons(area: Area) -> list[list[Ring]]:
    if area.type == "Polygon":
        return [[list(ring) for ring in area.coordinates]]
    return [[list(ring) for ring in polygon] for polygon in area.coordinates]


def point_in_area(point: tuple[float, float], area: Area) -> bool:
    return any(
        _inside(point, rings[0]) and not any(_inside(point, hole) for hole in rings[1:])
        for rings in _polygons(area)
    )


def distance_to_edges_m(point: tuple[float, float], area: Area) -> float:
    """Shortest distance from the point to any ring edge, in a local metric frame."""
    longitude, latitude = point
    scale = cos(radians(latitude)) * EARTH_RADIUS_M
    best = float("inf")
    for rings in _polygons(area):
        for ring in rings:
            for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:], strict=False):
                ax = radians(_shift(lon1, longitude)) * scale
                ay = radians(lat1 - latitude) * EARTH_RADIUS_M
                bx = radians(_shift(lon2, longitude)) * scale
                by = radians(lat2 - latitude) * EARTH_RADIUS_M
                dx, dy = bx - ax, by - ay
                length = dx * dx + dy * dy
                t = max(0.0, min(1.0, -(ax * dx + ay * dy) / length)) if length else 0.0
                best = min(best, sqrt((ax + t * dx) ** 2 + (ay + t * dy) ** 2))
    return best
