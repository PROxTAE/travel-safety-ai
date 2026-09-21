"""Unit tests for time/geography split, class distribution, and bias audit."""

from training.audit import (
    audit_critical_feature_nulls,
    audit_subgroups,
    compute_class_distribution,
    generate_bias_audit_report,
)
from training.labeling import LabeledRow
from training.split import perform_time_and_geography_split


def make_row(
    row_id: str, corridor_id: str, geo_group: str, dep_time: str, label: str
) -> LabeledRow:
    return LabeledRow(
        row_id=row_id,
        corridor_id=corridor_id,
        departure_time=dep_time,
        geography_group=geo_group,
        season="HOT",
        travel_mode="CAR",
        hazard_type="NONE",
        features={
            "corridor_official_closure_active": False,
            "corridor_extreme_alert_active": False,
            "hazard_intersection_fraction": 0.0,
            "max_weather_severity_ordinal": 0,
            "critical_evidence_coverage": 1.0,
            "critical_evidence_freshness_seconds": 3600,
        },
        label=label,
        label_method="DOCUMENTED_WEAK_SUPERVISION",
        primary_reason="CLEAR_CONDITIONS",
        heuristic_label="LOW",
        disagreement=False,
    )


def test_time_and_geography_split() -> None:
    rows = []
    # Create 20 instances across two corridors and sequential times
    for i in range(1, 21):
        dep = f"2024-05-{i:02d}T08:00:00Z"
        corridor = "C1" if i % 2 == 0 else "C2"
        group = "NORTH_CORRIDOR" if corridor == "C1" else "SOUTH_CORRIDOR"
        label = "LOW" if i < 15 else "HIGH"
        rows.append(make_row(f"R-{i}", corridor, group, dep, label))

    split = perform_time_and_geography_split(rows, random_seed=42)
    assert len(split.train_rows) > 0
    assert len(split.val_rows) > 0
    assert len(split.test_rows) > 0
    assert len(split.train_rows) + len(split.val_rows) + len(split.test_rows) == 20
    assert split.leakage_check_passed is True
    assert len(split.geography_groups) >= 2
    assert "NORTH_CORRIDOR" in split.geography_groups
    assert "SOUTH_CORRIDOR" in split.geography_groups


def test_class_distribution_and_bias_audit() -> None:
    rows = [
        make_row("R1", "C1", "NORTH_CORRIDOR", "2024-05-01T08:00:00Z", "LOW"),
        make_row("R2", "C1", "NORTH_CORRIDOR", "2024-05-02T08:00:00Z", "MEDIUM"),
        make_row("R3", "C2", "SOUTH_CORRIDOR", "2024-05-03T08:00:00Z", "HIGH"),
        make_row("R4", "C2", "SOUTH_CORRIDOR", "2024-05-04T08:00:00Z", "LOW"),
    ]
    dist = compute_class_distribution(rows)
    assert dist["LOW"] == 2
    assert dist["MEDIUM"] == 1
    assert dist["HIGH"] == 1

    subgroups = audit_subgroups(rows)
    assert subgroups["geography"]["NORTH_CORRIDOR"] == 2
    assert subgroups["geography"]["SOUTH_CORRIDOR"] == 2

    null_rates = audit_critical_feature_nulls(rows)
    assert null_rates["corridor_official_closure_active"] == 0.0

    split = perform_time_and_geography_split(rows)
    report = generate_bias_audit_report(split)
    assert report["total_rows"] == 4
    assert report["bias_checks"]["high_risk_represented"] is True
    assert "class_distribution_by_split" in report
