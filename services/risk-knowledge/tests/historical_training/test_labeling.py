"""Unit tests for labeling pipeline, disagreement reporting, and review sample generation."""

from training.features import FeatureVector
from training.labeling import (
    LABEL_HIGH,
    LABEL_LOW,
    LABEL_MEDIUM,
    assign_ground_truth_label,
    generate_disagreement_report,
    generate_review_sample,
    label_dataset_row,
)


def make_test_vector(overrides: dict) -> FeatureVector:
    values = {
        "route_distance_m": 100000.0,
        "route_duration_seconds": 3600.0,
        "route_transfer_count": 0,
        "corridor_official_closure_active": False,
        "corridor_official_evacuation_active": None,
        "corridor_extreme_alert_active": False,
        "hazard_intersection_fraction": 0.0,
        "max_weather_severity_ordinal": 0,
        "max_precipitation_probability": 0.0,
        "max_wind_gust_kmh": 10.0,
        "transport_disruption_severity": 0,
        "critical_evidence_coverage": 1.0,
        "critical_evidence_freshness_seconds": 3600,
    }
    values.update(overrides)
    return FeatureVector(
        schema_version="1.0.0",
        values=values,
        null_features=(),
        lineage={},
        prediction_cutoff="2024-05-01T00:00:00Z",
    )


def test_official_closure_forces_high_risk() -> None:
    # Even if weather is completely clear (ordinal 0), official closure forces HIGH
    fv = make_test_vector(
        {
            "corridor_official_closure_active": True,
            "max_weather_severity_ordinal": 0,
        }
    )
    label, method, reason = assign_ground_truth_label(fv.values)
    assert label == LABEL_HIGH
    assert method == "OFFICIAL_CLOSURE"
    assert reason == "OFFICIAL_CLOSURE_ACTIVE"


def test_official_extreme_alert_forces_high_risk() -> None:
    fv = make_test_vector(
        {
            "corridor_extreme_alert_active": True,
        }
    )
    label, method, reason = assign_ground_truth_label(fv.values)
    assert label == LABEL_HIGH
    assert method == "OFFICIAL_ALERT"
    assert reason == "OFFICIAL_EXTREME_ALERT"


def test_major_hazard_intersection_forces_high_risk() -> None:
    fv = make_test_vector(
        {
            "hazard_intersection_fraction": 0.25,
        }
    )
    label, method, reason = assign_ground_truth_label(fv.values)
    assert label == LABEL_HIGH
    assert method == "OFFICIAL_ALERT"
    assert reason == "SEVERE_HAZARD_INTERSECTION"


def test_moderate_hazard_or_weather_assigns_medium_risk() -> None:
    fv = make_test_vector(
        {
            "hazard_intersection_fraction": 0.05,
            "max_weather_severity_ordinal": 2,
        }
    )
    label, method, _ = assign_ground_truth_label(fv.values)
    assert label == LABEL_MEDIUM
    assert method == "DOCUMENTED_WEAK_SUPERVISION"


def test_clear_conditions_assigns_low_risk() -> None:
    fv = make_test_vector({})
    label, method, reason = assign_ground_truth_label(fv.values)
    assert label == LABEL_LOW
    assert method == "DOCUMENTED_WEAK_SUPERVISION"
    assert reason == "CLEAR_CONDITIONS_NORMAL_TRANSIT"


def test_disagreement_detection_and_reporting() -> None:
    # Case where closure is active (GT = HIGH), but weather is clear (Weak heuristic = LOW)
    fv_conflict = make_test_vector(
        {
            "corridor_official_closure_active": True,
            "max_weather_severity_ordinal": 0,
            "max_precipitation_probability": 0.0,
        }
    )
    corridor = {"corridor_id": "TH-NORTH-01", "geography_group": "NORTH_CORRIDOR", "mode": "CAR"}
    row1 = label_dataset_row(
        row_id="ROW-001",
        corridor=corridor,
        departure_time="2024-05-01T08:00:00Z",
        season="HOT",
        hazard_type="LANDSLIDE",
        feature_vector=fv_conflict,
    )
    assert row1.label == LABEL_HIGH
    assert row1.heuristic_label == LABEL_LOW
    assert row1.disagreement is True

    # Case where both agree LOW
    fv_agree = make_test_vector({})
    row2 = label_dataset_row(
        row_id="ROW-002",
        corridor=corridor,
        departure_time="2024-05-02T08:00:00Z",
        season="HOT",
        hazard_type="NONE",
        feature_vector=fv_agree,
    )
    assert row2.disagreement is False

    report = generate_disagreement_report([row1, row2])
    assert report["total_rows_evaluated"] == 2
    assert report["disagreement_count"] == 1
    assert report["disagreement_rate"] == 0.5
    assert len(report["sample_disagreements"]) == 1


def test_review_sample_generation() -> None:
    corridor = {"corridor_id": "TH-NORTH-01", "geography_group": "NORTH_CORRIDOR", "mode": "CAR"}
    # Disagreement row
    fv_disagree = make_test_vector({"corridor_official_closure_active": True})
    r1 = label_dataset_row("R1", corridor, "2024-05-01T08:00:00Z", "HOT", "LANDSLIDE", fv_disagree)

    # Boundary row (hazard fraction = 0.12)
    fv_bound = make_test_vector({"hazard_intersection_fraction": 0.12})
    r2 = label_dataset_row("R2", corridor, "2024-05-02T08:00:00Z", "HOT", "FLOOD", fv_bound)

    # Normal row
    fv_norm = make_test_vector({})
    r3 = label_dataset_row("R3", corridor, "2024-05-03T08:00:00Z", "HOT", "NONE", fv_norm)

    samples = generate_review_sample([r1, r2, r3])
    # Both r1 (disagreement) and r2 (boundary) must be included
    row_ids = [s["row_id"] for s in samples]
    assert "R1" in row_ids
    assert "R2" in row_ids
    for s in samples:
        assert s["review_status"] == "PENDING_REVIEW"
