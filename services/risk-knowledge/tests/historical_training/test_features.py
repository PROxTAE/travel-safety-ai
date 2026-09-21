"""Unit tests for feature extraction and cutoff leakage prevention."""

from datetime import UTC, datetime

from training.features import (
    FEATURE_NAMES,
    NON_NULLABLE_FEATURES,
    WEATHER_CODE_TO_SEVERITY,
    extract_features,
    filter_records_before_cutoff,
    haversine_distance_m,
    parse_utc_timestamp,
)


def test_parse_utc_timestamp() -> None:
    dt = parse_utc_timestamp("2024-05-15T10:00:00Z")
    assert dt.year == 2024
    assert dt.tzinfo == UTC


def test_haversine_distance() -> None:
    # Bangkok to Ayutthaya (~70 km)
    bkk = [100.5018, 13.7563]
    ayutthaya = [100.5775, 14.3532]
    dist = haversine_distance_m(bkk, ayutthaya)
    assert 60000.0 < dist < 80000.0


def test_filter_records_before_cutoff() -> None:
    cutoff = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    records = [
        {"id": "rec-1", "observed_at": "2024-05-30T12:00:00Z"},
        {"id": "rec-2", "observed_at": "2024-06-01T00:00:00Z"},  # exact cutoff
        {"id": "rec-3", "observed_at": "2024-06-01T01:00:00Z"},  # after cutoff -> leaked
        {"id": "rec-4", "observed_at": "2024-06-15T00:00:00Z"},  # future
    ]
    filtered = filter_records_before_cutoff(records, cutoff)
    assert filtered is not None
    assert len(filtered) == 2
    ids = [r["id"] for r in filtered]
    assert "rec-1" in ids
    assert "rec-2" in ids
    assert "rec-3" not in ids
    assert "rec-4" not in ids


def test_weather_code_severity_mapping() -> None:
    assert WEATHER_CODE_TO_SEVERITY[0] == 0  # Clear -> INFO
    assert WEATHER_CODE_TO_SEVERITY[61] == 2  # Rain -> MODERATE
    assert WEATHER_CODE_TO_SEVERITY[65] == 3  # Heavy rain -> SEVERE
    assert WEATHER_CODE_TO_SEVERITY[99] == 4  # Violent thunderstorm with hail -> EXTREME


def test_extract_features_schema_conformance() -> None:
    corridor = {
        "corridor_id": "TH-NORTH-01",
        "distance_m": 692000.0,
        "duration_seconds": 32400.0,
        "transfers": 0,
        "mode": "CAR",
        "waypoints": [[100.5018, 13.7563], [98.9853, 18.7883]],
    }
    weather = {
        "hourly": {
            "time": ["2024-05-01T00:00:00Z", "2024-05-01T01:00:00Z"],
            "weather_code": [0, 65],
            "precipitation": [0.0, 15.0],
            "wind_gusts_10m": [10.0, 45.0],
        }
    }
    disasters = [
        {
            "event_type": "FLOOD",
            "geometry": [100.5018, 13.7563],
            "severity": "SEVERE",
            "radius_m": 50000.0,
            "observed_at": "2024-05-01T00:00:00Z",
        }
    ]

    fv = extract_features(
        corridor=corridor,
        departure_time="2024-05-01T08:00:00Z",
        prediction_cutoff="2024-05-01T06:00:00Z",
        weather_data=weather,
        disasters=disasters,
        source_checksums={"weather": "sha256:abc", "disaster": "sha256:def"},
    )

    assert fv.schema_version == "1.0.0"
    for name in FEATURE_NAMES:
        assert name in fv.values

    # Check non-nullable features are populated
    for name in NON_NULLABLE_FEATURES:
        assert fv.values[name] is not None

    assert fv.values["route_distance_m"] == 692000.0
    assert fv.values["route_duration_seconds"] == 32400.0
    assert fv.values["route_transfer_count"] == 0
    assert fv.values["hazard_intersection_fraction"] > 0.0
    assert fv.lineage["corridor_id"] == "TH-NORTH-01"
    assert "weather" in fv.lineage["source_checksums"]


def test_extract_features_handles_minimal_corridor() -> None:
    corridor = {"corridor_id": "MIN-01", "distance_m": 1000.0, "duration_seconds": 60.0}
    fv = extract_features(
        corridor=corridor,
        departure_time="2024-05-01T08:00:00Z",
        prediction_cutoff="2024-05-01T06:00:00Z",
    )
    assert fv.values["route_distance_m"] == 1000.0
    assert fv.values["route_duration_seconds"] == 60.0
