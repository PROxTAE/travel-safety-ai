"""Class distribution and bias audit reporting for Module 06 risk dataset.

Provides:
- Overall and per-split class distribution (LOW / MEDIUM / HIGH)
- Subgroup representations (geography, season, hazard type, travel mode)
- Bias and disparity audit (HIGH class representation, null rates, imbalance checks)
"""

from __future__ import annotations

from typing import Any

from training.labeling import LabeledRow
from training.split import SplitResult


def compute_class_distribution(rows: list[LabeledRow]) -> dict[str, int]:
    """Compute exact frequency count of each risk level."""
    distribution: dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for r in rows:
        distribution[r.label] = distribution.get(r.label, 0) + 1
    return distribution


def audit_subgroups(rows: list[LabeledRow]) -> dict[str, dict[str, int]]:
    """Compute frequency counts across required evaluation subgroups."""
    by_geography: dict[str, int] = {}
    by_season: dict[str, int] = {}
    by_mode: dict[str, int] = {}
    by_hazard: dict[str, int] = {}

    for r in rows:
        by_geography[r.geography_group] = by_geography.get(r.geography_group, 0) + 1
        by_season[r.season] = by_season.get(r.season, 0) + 1
        by_mode[r.travel_mode] = by_mode.get(r.travel_mode, 0) + 1
        by_hazard[r.hazard_type] = by_hazard.get(r.hazard_type, 0) + 1

    return {
        "geography": by_geography,
        "season": by_season,
        "travel_mode": by_mode,
        "hazard_type": by_hazard,
    }


def audit_critical_feature_nulls(rows: list[LabeledRow]) -> dict[str, float]:
    """Calculate null rate for critical safety features."""
    if not rows:
        return {}
    critical_names = (
        "corridor_official_closure_active",
        "corridor_extreme_alert_active",
        "hazard_intersection_fraction",
        "max_weather_severity_ordinal",
        "critical_evidence_coverage",
        "critical_evidence_freshness_seconds",
    )
    rates: dict[str, float] = {}
    n = len(rows)
    for name in critical_names:
        null_count = sum(1 for r in rows if r.features.get(name) is None)
        rates[name] = round(null_count / n, 4)
    return rates


def generate_bias_audit_report(split_result: SplitResult) -> dict[str, Any]:
    """Generate complete bias audit report covering class distributions and subgroup equity."""
    all_rows = split_result.train_rows + split_result.val_rows + split_result.test_rows
    total_count = len(all_rows)

    overall_classes = compute_class_distribution(all_rows)
    train_classes = compute_class_distribution(split_result.train_rows)
    val_classes = compute_class_distribution(split_result.val_rows)
    test_classes = compute_class_distribution(split_result.test_rows)

    subgroups = audit_subgroups(all_rows)
    critical_null_rates = audit_critical_feature_nulls(all_rows)

    # Bias assessment flags
    high_count = overall_classes.get("HIGH", 0)
    high_ratio = high_count / max(1, total_count)
    high_risk_represented = high_count > 0

    # Warning if high risk is severely underrepresented (< 5%)
    severe_imbalance = high_ratio < 0.05

    # Check for empty subgroups in test
    test_subgroups = audit_subgroups(split_result.test_rows)
    unrepresented_in_test: list[str] = []
    for dim, counts in subgroups.items():
        for category in counts:
            if test_subgroups.get(dim, {}).get(category, 0) == 0:
                unrepresented_in_test.append(f"{dim}:{category}")

    return {
        "audit_version": "1.0.0",
        "total_rows": total_count,
        "class_distribution_overall": overall_classes,
        "class_distribution_by_split": {
            "train": train_classes,
            "val": val_classes,
            "test": test_classes,
        },
        "class_proportions": {
            k: round(v / max(1, total_count), 4) for k, v in overall_classes.items()
        },
        "subgroup_distributions": subgroups,
        "critical_feature_null_rates": critical_null_rates,
        "bias_checks": {
            "high_risk_represented": high_risk_represented,
            "severe_class_imbalance": severe_imbalance,
            "high_risk_ratio": round(high_ratio, 4),
            "unrepresented_subgroups_in_test": unrepresented_in_test,
            "passed_safety_guardrails": high_risk_represented and not severe_imbalance,
        },
        "findings": (
            f"Dataset contains {total_count} rows with "
            f"{overall_classes.get('HIGH', 0)} HIGH-risk cases "
            f"({round(high_ratio * 100, 1)}%). Ground-truth labels strictly "
            "preserve official closures and warnings without synthetic oversampling."
        ),
    }
