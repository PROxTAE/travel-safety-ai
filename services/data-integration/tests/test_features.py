"""Feature vector cases built from module 04 captures in tests/fixtures/m04-*.json.

Open-Meteo Bangkok and USGS captures are HTTP 200 responses; the MTA record is a
real GTFS-Realtime status that the producer marked STALE. Route lines and hazard
squares are test-only geometries placed on captured coordinates, and expected
values are hand-computed from the captured measurements.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.domain.canonical import (
    DataQuality,
    DisasterEvent,
    GeoLineString,
    RouteCandidate,
    RouteSegment,
    TransportStatus,
    WeatherForecastPoint,
)
from app.pipeline.corridor import sample_route
from app.pipeline.features import (
    FeatureInputs,
    FeaturePolicy,
    FeatureVector,
    build_features,
    feature_schema,
)

FIXTURES = Path(__file__).parent / "fixtures"
AFTER_CAPTURE = datetime(2026, 9, 20, 18, tzinfo=UTC)
BANGKOK = [(100.495865, 13.743409), (100.505865, 13.743409)]
POLICY = FeaturePolicy(
    weather_radius_m=2000, weather_time_tolerance_seconds=1200, transport_time_tolerance_seconds=300
)


def record(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


def bangkok_weather(**changes: Any) -> WeatherForecastPoint:
    return WeatherForecastPoint.model_validate(record("m04-weather-forecast-points.json") | changes)


def usgs_event(**changes: Any) -> DisasterEvent:
    return DisasterEvent.model_validate(record("m04-usgs-event.json") | changes)


def square(west: float, east: float, south: float, north: float) -> dict[str, Any]:
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"type": "Polygon", "coordinates": [ring]}


def build(
    *,
    weather: list[WeatherForecastPoint] | None = None,
    disasters: list[DisasterEvent] | None = None,
    transport: list[TransportStatus] | None = None,
    segments: list[RouteSegment] | None = None,
    line: list[tuple[float, float]] = BANGKOK,
    departure: datetime = datetime(2026, 9, 19, tzinfo=UTC),
    recommendation_at: datetime = AFTER_CAPTURE,
    mode: str = "CAR",
    spacing_m: float = 1000,
) -> FeatureVector:
    base = RouteCandidate.model_validate(record("m04-route-candidates.json"))
    route = base.model_copy(
        update={
            "geometry": GeoLineString(type="LineString", coordinates=line),
            "segments": segments or [],
            "mode": mode,
        }
    )
    samples = sample_route(
        route.geometry, departure_at=departure, duration_seconds=3600, max_spacing_m=spacing_m
    )
    sources: dict[str, DataQuality] = {"route": route.quality}
    for name, records in (("weather", weather), ("disaster", disasters), ("transport", transport)):
        if records:
            sources[name] = records[0].quality
    inputs = FeatureInputs(
        route, samples, recommendation_at, weather, disasters, transport, sources
    )
    return build_features(inputs, POLICY)


def test_values_follow_module_06_schema_names_and_order() -> None:
    vector = build(weather=[], disasters=[], transport=[])
    assert vector.schema_version == "1.0.0"
    assert list(vector.values) == [f["name"] for f in feature_schema()["features"]]


def test_captured_bangkok_forecast_uses_schema_units() -> None:
    values = build(weather=[bangkok_weather()], disasters=[]).values
    # Open-Meteo 39 percent becomes the schema ratio 0.39.
    assert values["max_precipitation_probability"] == pytest.approx(0.39)
    assert values["max_wind_gust_kmh"] == 19.8
    # Open-Meteo gives no severity class, which maps to UNKNOWN (5), never INFO.
    assert values["max_weather_severity_ordinal"] == 5
    assert values["route_distance_m"] == 73688.3
    assert values["route_transfer_count"] == 0
    # One point at the start covers the first of three samples in time.
    assert values["critical_evidence_coverage"] == pytest.approx(1 / 3)


def test_unavailable_sources_stay_null_not_false_or_zero() -> None:
    vector = build()
    for name in (
        "corridor_official_closure_active",
        "corridor_extreme_alert_active",
        "hazard_intersection_fraction",
        "max_weather_severity_ordinal",
        "max_precipitation_probability",
        "critical_evidence_freshness_seconds",
    ):
        assert vector.values[name] is None
        assert name in vector.null_features
    assert vector.values["critical_evidence_coverage"] == 0.0


def test_answered_empty_alerts_prove_absence_except_evacuation() -> None:
    values = build(weather=[], disasters=[]).values
    assert values["corridor_official_closure_active"] is False
    assert values["corridor_extreme_alert_active"] is False
    assert values["hazard_intersection_fraction"] == 0.0
    # No producer publishes evacuation orders, so absence is never asserted.
    assert values["corridor_official_evacuation_active"] is None


def test_official_quake_with_unknown_severity_cannot_rule_out_extreme() -> None:
    values = build(
        weather=[],
        disasters=[usgs_event()],
        line=[(-171.3856, 52.8594), (-171.3756, 52.8594)],
        departure=datetime(2026, 9, 17, 14, 19, 52, tzinfo=UTC),
    ).values
    assert values["corridor_extreme_alert_active"] is None
    assert values["corridor_official_closure_active"] is False
    # A point event has no area for the route to pass through.
    assert values["hazard_intersection_fraction"] == 0.0


@pytest.mark.parametrize(
    ("line", "area"),
    [
        # 0.03 degrees of route; the square spans the middle 0.01 degrees.
        ([(-171.39, 52.855), (-171.36, 52.855)], square(-171.38, -171.37, 52.85, 52.86)),
        # The Fiji route crosses 180; the square spans 0.2 of its 0.6 degrees.
        ([(179.57103, -16.5), (-179.82872, -16.5)], square(179.9, -179.9, -16.6, -16.4)),
    ],
)
def test_hazard_area_fraction_matches_hand_computed_third(
    line: list[tuple[float, float]], area: dict[str, Any]
) -> None:
    event = usgs_event(geometry=area, effective_at="2026-09-17T00:00:00Z")
    values = build(
        weather=[],
        disasters=[event],
        line=line,
        departure=datetime(2026, 9, 17, 14, tzinfo=UTC),
        spacing_m=100,
    ).values
    # Tolerance covers one 100 m sample interval at either square edge.
    assert values["hazard_intersection_fraction"] == pytest.approx(1 / 3, abs=0.05)


def test_stale_realtime_feed_is_unknown_disruption_for_transit() -> None:
    status = TransportStatus.model_validate(record("m04-transport-statuses.json"))
    segment = RouteSegment(
        segment_id="s1",
        mode="TRAIN",
        from_name=status.origin_stop.name,
        to_name=status.destination_stop.name,
        distance_m=1000,
        duration_seconds=600,
        departure_time=status.estimated_departure or status.scheduled_departure,
        transport_status_id=status.id,
    )
    values = build(
        weather=[], disasters=[], transport=[status], segments=[segment], mode="TRAIN"
    ).values
    # The captured record says DELAYED, but a STALE feed cannot vouch for it now.
    assert values["transport_disruption_severity"] == 4
    assert values["critical_evidence_coverage"] == 0.0


def test_freshness_is_oldest_critical_source_age() -> None:
    values = build(weather=[bangkok_weather()], disasters=[usgs_event()]).values
    ages = [bangkok_weather().quality.freshness_seconds, usgs_event().quality.freshness_seconds]
    assert values["critical_evidence_freshness_seconds"] == max(a for a in ages if a is not None)


def test_evidence_fetched_after_recommendation_is_excluded() -> None:
    before_fetch = datetime(2026, 9, 20, 17, tzinfo=UTC)
    values = build(weather=[bangkok_weather()], disasters=[], recommendation_at=before_fetch).values
    assert values["max_wind_gust_kmh"] is None
    assert values["critical_evidence_coverage"] == 0.0


def test_build_is_deterministic() -> None:
    first = build(weather=[bangkok_weather()], disasters=[usgs_event()])
    second = build(weather=[bangkok_weather()], disasters=[usgs_event()])
    assert json.dumps(first.values) == json.dumps(second.values)


def test_schema_carries_lead_decision_on_official_alerts() -> None:
    """Issues #43 and #44: nullable alert flags; evacuation is not critical yet."""
    features = {f["name"]: f for f in feature_schema()["features"]}
    for name in (
        "corridor_official_closure_active",
        "corridor_official_evacuation_active",
        "corridor_extreme_alert_active",
    ):
        assert features[name]["nullable"] is True
    assert features["corridor_official_evacuation_active"]["critical"] is False
    assert features["corridor_official_closure_active"]["critical"] is True
