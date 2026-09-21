"""ETA cases use the captured Fiji weather pair and USGS earthquake from module 04.

Provider HTTP 200 captures: Open-Meteo 2026-09-20T14:43:47Z;
USGS 2026-09-19T07:45:38Z. Routes here are test-only derived geometries.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain.canonical import (
    DisasterEvent,
    GeoLineString,
    RouteSegment,
    TransportStatus,
    WeatherForecastPoint,
)
from app.pipeline.alignment import align_disaster, align_transport, align_weather, weather_coverage
from app.pipeline.corridor import sample_route


def fiji_weather(
    longitude: float, latitude: float, valid_at: str, source_id: str, temperature_c: float
) -> WeatherForecastPoint:
    return WeatherForecastPoint.model_validate(
        {
            "id": source_id,
            "location": {"type": "Point", "coordinates": [longitude, latitude]},
            "valid_at": valid_at,
            "temperature_c": temperature_c,
            "precipitation_mm": 0.0,
            "severity": "UNKNOWN",
            "quality": {"status": "FRESH", "flags": ["MISSING"]},
            "source": {
                "source_id": source_id,
                "provider": "open_meteo_forecast",
                "authority": "LICENSED_PROVIDER",
                "fetched_at": "2026-09-20T14:43:47Z",
                "schema_version": "1.0.0",
            },
        }
    )


def test_fiji_weather_aligns_to_both_sides_of_dateline() -> None:
    line = GeoLineString(
        type="LineString",
        coordinates=[
            (179.57103, -16.55536),
            (-179.82872, -16.414762),
        ],
    )
    samples = sample_route(
        line,
        departure_at=datetime(2026, 9, 20, 20, tzinfo=UTC),
        duration_seconds=3600,
        max_spacing_m=5000,
    )
    west = fiji_weather(179.57103, -16.55536, "2026-09-20T20:00:00Z", "fiji-west", 23.3)
    east = fiji_weather(-179.82872, -16.414762, "2026-09-20T21:00:00Z", "fiji-east", 23.5)
    assert (
        align_weather(samples, west, radius_m=1000, time_tolerance_seconds=300).status == "MATCHED"
    )
    assert (
        align_weather(samples, east, radius_m=1000, time_tolerance_seconds=300).status == "MATCHED"
    )
    assert align_weather(samples, east, radius_m=1000, time_tolerance_seconds=0).status == "MATCHED"
    coverage = weather_coverage(samples, [west, east], radius_m=1000, time_tolerance_seconds=300)
    assert 0 < coverage < 1


def test_event_ends_before_route_eta_is_excluded() -> None:
    start = datetime(2026, 9, 17, 14, 19, 52, tzinfo=UTC)
    line = GeoLineString(
        type="LineString",
        coordinates=[
            (-171.3856, 52.8594),
            (-171.3756, 52.8594),
        ],
    )
    samples = sample_route(line, departure_at=start, duration_seconds=600, max_spacing_m=1000)
    raw = {
        "event_id": "us7000ti1p",
        "event_type": "EARTHQUAKE",
        "title": "M 6.5 - 169 km W of Nikolski, Alaska",
        "severity": "UNKNOWN",
        "geometry": {"type": "Point", "coordinates": [-171.3756, 52.8594]},
        "effective_at": "2026-09-17T14:19:52.210Z",
        "official": True,
        "quality": {"status": "FRESH"},
        "source": {
            "source_id": "usgs:us7000ti1p",
            "provider": "usgs",
            "authority": "OFFICIAL",
            "fetched_at": "2026-09-19T07:45:38Z",
            "schema_version": "1.0.0",
        },
    }
    active = DisasterEvent.model_validate(raw)
    assert align_disaster(samples, active, radius_m=1000).status == "MATCHED"
    ended = active.model_copy(update={"ends_at": start + timedelta(minutes=1)})
    result = align_disaster(samples, ended, radius_m=1000)
    assert result.status == "OUTSIDE_COVERAGE"
    assert result.reason == "EVENT_WINDOW"


def test_transport_requires_linked_trip_stops_and_time() -> None:
    """Stop names from MTA static GTFS HTTP 200 capture, 2026-09-20T13:33:21Z."""
    departure = datetime(2026, 9, 20, 13, 33, 21, tzinfo=UTC)
    segment = RouteSegment.model_validate(
        {
            "segment_id": "mta:A02N-A03N",
            "mode": "TRAIN",
            "from_name": "Inwood-207 St",
            "to_name": "Dyckman St",
            "distance_m": 1000,
            "duration_seconds": 180,
            "departure_time": departure.isoformat(),
            "transport_status_id": "mta:A02N-A03N",
        }
    )
    status = TransportStatus.model_validate(
        {
            "id": "mta:A02N-A03N",
            "mode": "TRAIN",
            "operator": "MTA",
            "service_number": "A",
            "status": "UNKNOWN",
            "origin_stop": {"name": "Inwood-207 St"},
            "destination_stop": {"name": "Dyckman St"},
            "scheduled_departure": departure.isoformat(),
            "quality": {"status": "PARTIAL", "flags": ["INCOMPLETE"]},
            "source": {
                "source_id": "mta:captured-trip",
                "provider": "mta",
                "authority": "OFFICIAL",
                "fetched_at": "2026-09-20T13:33:21Z",
                "schema_version": "1.0.0",
            },
        }
    )
    assert align_transport(segment, status, time_tolerance_seconds=60).status == "MATCHED"
    wrong = segment.model_copy(update={"transport_status_id": "another-trip"})
    assert align_transport(wrong, status, time_tolerance_seconds=60).status == "OUTSIDE_COVERAGE"
    missing = status.model_copy(update={"service_number": None})
    assert align_transport(segment, missing, time_tolerance_seconds=60).status == "UNAVAILABLE"


def _usgs_area(geometry: dict) -> DisasterEvent:
    """Variant of the captured USGS event carrying an area instead of a point (#45)."""
    raw = json.loads((Path(__file__).parent / "fixtures" / "m04-usgs-event.json").read_text(
        encoding="utf-8"))["records"][0]  # fmt: skip
    # The capture is STALE, which alignment rightly reports; FRESH isolates the geometry.
    return DisasterEvent.model_validate(
        raw
        | {
            "geometry": geometry,
            "effective_at": "2026-09-18T00:00:00Z",
            "quality": raw["quality"] | {"status": "FRESH"},
        }
    )


def _square(west: float, south: float, east: float, north: float) -> list:
    return [[[west, south], [east, south], [east, north], [west, north], [west, south]]]


def _bangkok_samples():
    line = GeoLineString(type="LineString", coordinates=[(100.49, 13.74), (100.51, 13.74)])
    return sample_route(
        line, departure_at=datetime(2026, 9, 19, tzinfo=UTC), duration_seconds=600,
        max_spacing_m=500,
    )  # fmt: skip


def test_polygon_crossing_the_route_matches_at_zero_distance() -> None:
    samples = _bangkok_samples()
    event = _usgs_area({"type": "Polygon", "coordinates": _square(100.495, 13.73, 100.505, 13.75)})
    result = align_disaster(samples, event, radius_m=0)
    assert (result.status, result.distance_m) == ("MATCHED", 0.0)
    # The ETA is the first sample inside the square, not the route start.
    assert result.route_eta > samples[0].eta


def test_polygon_edge_near_the_route_uses_edge_distance_not_vertices() -> None:
    # The square's lower edge runs 0.002 deg (about 222 m) north of the route at 13.74,
    # while its nearest vertex is over 1 km away along the route direction.
    area = _square(100.4, 13.742, 100.6, 13.8)
    result = align_disaster(
        _bangkok_samples(), _usgs_area({"type": "Polygon", "coordinates": area}), radius_m=300
    )
    assert result.status == "MATCHED"
    assert 200 < result.distance_m < 240


def test_far_multipolygon_is_outside_coverage() -> None:
    far = {"type": "MultiPolygon", "coordinates": [_square(101.0, 14.0, 101.1, 14.1)]}
    result = align_disaster(_bangkok_samples(), _usgs_area(far), radius_m=5000)
    assert result.status == "OUTSIDE_COVERAGE"
    assert result.reason == "DISTANCE"
