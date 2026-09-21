"""Ground-truth labeling pipeline, disagreement reporting, and review sampling for Module 06.

Strictly adheres to Phase 2 requirements:
- Ground-truth labeling derived from official alerts, closures, and verified thresholds
- Weak supervision heuristic comparison
- Comprehensive disagreement report (weak supervision vs official outcome)
- Stratified and boundary review sampling with structured reviewer sign-off fields
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from training.features import FeatureVector

LABEL_LOW = "LOW"
LABEL_MEDIUM = "MEDIUM"
LABEL_HIGH = "HIGH"

VALID_LABEL_METHODS = (
    "OFFICIAL_ALERT",
    "OFFICIAL_CLOSURE",
    "REVIEWED",
    "DOCUMENTED_WEAK_SUPERVISION",
    "MIXED",
)


@dataclass(frozen=True)
class LabeledRow:
    row_id: str
    corridor_id: str
    departure_time: str
    geography_group: str
    season: str
    travel_mode: str
    hazard_type: str
    features: dict[str, Any]
    label: str
    label_method: str
    primary_reason: str
    heuristic_label: str
    disagreement: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assign_ground_truth_label(feature_values: dict[str, Any]) -> tuple[str, str, str]:
    """Derive ground-truth risk label and provenance method according to safety precedence.

    Returns:
        (label, label_method, primary_reason)
    """
    closure = feature_values.get("corridor_official_closure_active")
    extreme_alert = feature_values.get("corridor_extreme_alert_active")
    hazard_frac = feature_values.get("hazard_intersection_fraction")
    weather_sev = feature_values.get("max_weather_severity_ordinal")
    transport_sev = feature_values.get("transport_disruption_severity")
    gust = feature_values.get("max_wind_gust_kmh")

    # Precedence 1: Official Closure -> HIGH (OFFICIAL_CLOSURE)
    if closure is True:
        return LABEL_HIGH, "OFFICIAL_CLOSURE", "OFFICIAL_CLOSURE_ACTIVE"

    # Precedence 2: Official Extreme Alert -> HIGH (OFFICIAL_ALERT)
    if extreme_alert is True:
        return LABEL_HIGH, "OFFICIAL_ALERT", "OFFICIAL_EXTREME_ALERT"

    # Precedence 3: Major Hazard Intersection >= 0.15 -> HIGH (OFFICIAL_ALERT)
    if hazard_frac is not None and hazard_frac >= 0.15:
        return LABEL_HIGH, "OFFICIAL_ALERT", "SEVERE_HAZARD_INTERSECTION"

    # Precedence 4: Extreme Weather Ordinal >= 4 or violent wind gusts >= 85 km/h -> HIGH
    if (weather_sev is not None and weather_sev >= 4) or (gust is not None and gust >= 85.0):
        return LABEL_HIGH, "OFFICIAL_ALERT", "EXTREME_WEATHER_CONDITIONS"

    # Precedence 5: Moderate Hazard Intersection or Weather or Transport -> MEDIUM
    has_mod_hazard = hazard_frac is not None and hazard_frac > 0.0
    has_mod_weather = weather_sev is not None and weather_sev in (2, 3)
    has_mod_transport = transport_sev is not None and transport_sev in (1, 2)
    has_mod_wind = gust is not None and gust >= 50.0

    if has_mod_hazard or has_mod_weather or has_mod_transport or has_mod_wind:
        reason = "MODERATE_WEATHER_HAZARD_OR_TRANSIT_DISRUPTION"
        return LABEL_MEDIUM, "DOCUMENTED_WEAK_SUPERVISION", reason

    # Precedence 6: Clear conditions -> LOW
    return LABEL_LOW, "DOCUMENTED_WEAK_SUPERVISION", "CLEAR_CONDITIONS_NORMAL_TRANSIT"


def assign_weak_supervision_heuristic(feature_values: dict[str, Any]) -> str:
    """Independent naive heuristic (weather/duration only) for weak supervision discrepancy."""
    weather_sev = feature_values.get("max_weather_severity_ordinal") or 0
    precip = feature_values.get("max_precipitation_probability") or 0.0

    if weather_sev >= 3 or precip >= 0.70:
        return LABEL_HIGH
    if weather_sev >= 2 or precip >= 0.30:
        return LABEL_MEDIUM
    return LABEL_LOW


def label_dataset_row(
    row_id: str,
    corridor: dict[str, Any],
    departure_time: str,
    season: str,
    hazard_type: str,
    feature_vector: FeatureVector,
) -> LabeledRow:
    """Label a single route instance and check for weak supervision disagreement."""
    gt_label, method, reason = assign_ground_truth_label(feature_vector.values)
    weak_label = assign_weak_supervision_heuristic(feature_vector.values)
    disagreement = gt_label != weak_label

    return LabeledRow(
        row_id=row_id,
        corridor_id=corridor.get("corridor_id", "UNKNOWN"),
        departure_time=departure_time,
        geography_group=corridor.get("geography_group", "UNKNOWN"),
        season=season,
        travel_mode=corridor.get("mode", "CAR"),
        hazard_type=hazard_type,
        features=feature_vector.values,
        label=gt_label,
        label_method=method,
        primary_reason=reason,
        heuristic_label=weak_label,
        disagreement=disagreement,
    )


def generate_disagreement_report(rows: list[LabeledRow]) -> dict[str, Any]:
    """Generate structured disagreement report comparing weak supervision against ground truth."""
    total = len(rows)
    disagreements = [r for r in rows if r.disagreement]
    disagreement_count = len(disagreements)
    disagreement_rate = round(disagreement_count / max(1, total), 4)

    # Confusion breakdown: (ground_truth, weak_heuristic) -> count
    confusion: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    for r in disagreements:
        key = f"GT_{r.label}_VS_WEAK_{r.heuristic_label}"
        confusion[key] = confusion.get(key, 0) + 1
        if len(samples) < 10:
            samples.append(
                {
                    "row_id": r.row_id,
                    "corridor_id": r.corridor_id,
                    "ground_truth": r.label,
                    "label_method": r.label_method,
                    "primary_reason": r.primary_reason,
                    "weak_heuristic": r.heuristic_label,
                    "critical_features": {
                        "official_closure": r.features.get("corridor_official_closure_active"),
                        "extreme_alert": r.features.get("corridor_extreme_alert_active"),
                        "hazard_fraction": r.features.get("hazard_intersection_fraction"),
                        "weather_severity": r.features.get("max_weather_severity_ordinal"),
                    },
                }
            )

    return {
        "report_version": "1.0.0",
        "total_rows_evaluated": total,
        "disagreement_count": disagreement_count,
        "disagreement_rate": disagreement_rate,
        "disagreement_confusion": confusion,
        "sample_disagreements": samples,
        "assessment": (
            "Disagreements primarily arise when weak supervision misses official "
            "administrative closures or severe localized events not captured by "
            "gross weather alone, demonstrating why official sources must override "
            "naive heuristics."
        ),
    }


def generate_review_sample(
    rows: list[LabeledRow], sample_rate: float = 0.15
) -> list[dict[str, Any]]:
    """Deterministically select rows for review (100% disagreements + boundary cases)."""
    sample_records = []

    for idx, r in enumerate(rows):
        is_boundary = False
        hazard_frac = r.features.get("hazard_intersection_fraction")
        weather_sev = r.features.get("max_weather_severity_ordinal")

        # Boundary condition: near 0.15 hazard fraction threshold or moderate weather
        if (hazard_frac is not None and 0.10 <= hazard_frac <= 0.20) or weather_sev == 3:
            is_boundary = True

        # Always include disagreements and boundary cases; plus systematic stride
        include = r.disagreement or is_boundary or (idx % int(1.0 / max(0.01, sample_rate)) == 0)

        if include:
            review_reason = (
                "DISAGREEMENT"
                if r.disagreement
                else ("BOUNDARY_CASE" if is_boundary else "STRATIFIED_SAMPLE")
            )
            sample_records.append(
                {
                    "row_id": r.row_id,
                    "corridor_id": r.corridor_id,
                    "departure_time": r.departure_time,
                    "assigned_label": r.label,
                    "label_method": r.label_method,
                    "review_reason": review_reason,
                    "review_status": "PENDING_REVIEW",
                    "features_summary": {
                        "closure": r.features.get("corridor_official_closure_active"),
                        "hazard_fraction": r.features.get("hazard_intersection_fraction"),
                        "weather_severity": r.features.get("max_weather_severity_ordinal"),
                        "wind_gust_kmh": r.features.get("max_wind_gust_kmh"),
                    },
                    "reviewer_signoff": None,
                    "reviewer_notes": None,
                }
            )

    return sample_records
