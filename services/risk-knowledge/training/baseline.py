"""Leakage-safe calibrated baseline training and evaluation for Phase 3."""

from __future__ import annotations

import hashlib
import json
import math
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_recall_fscore_support,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, label_binarize

from training.features import FEATURE_NAMES

LABELS = ("LOW", "MEDIUM", "HIGH")
REASON_BY_FEATURE = {
    "route_distance_m": "TRANSPORT_DISRUPTION",
    "route_duration_seconds": "TRANSPORT_DISRUPTION",
    "route_transfer_count": "TRANSPORT_DISRUPTION",
    "corridor_official_closure_active": "OFFICIAL_CLOSURE",
    "corridor_official_evacuation_active": "OFFICIAL_EVACUATION",
    "corridor_extreme_alert_active": "EXTREME_WARNING_CORRIDOR",
    "hazard_intersection_fraction": "DISASTER_CORRIDOR_INTERSECTION",
    "max_weather_severity_ordinal": "SEVERE_WEATHER_CORRIDOR",
    "max_precipitation_probability": "SEVERE_WEATHER_CORRIDOR",
    "max_wind_gust_kmh": "SEVERE_WEATHER_CORRIDOR",
    "transport_disruption_severity": "TRANSPORT_DISRUPTION",
    "critical_evidence_coverage": "LIMITED_CRITICAL_COVERAGE",
    "critical_evidence_freshness_seconds": "STALE_CRITICAL_EVIDENCE",
}


@dataclass(frozen=True)
class TrainingResult:
    artifact: Path
    checksum: str
    metrics: dict[str, Any]
    model_card: Path
    manifest: Path


def _matrix(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    values = [[row["features"].get(name) for name in FEATURE_NAMES] for row in rows]
    labels = [row["label"] for row in rows]
    return np.asarray(values, dtype=object), np.asarray(labels)


def _folds(rows: list[dict[str, Any]]) -> list[tuple[np.ndarray, np.ndarray]]:
    """Build deterministic held-out geography folds; time ordering remains intact."""
    groups = sorted({str(row["geography_group"]) for row in rows})
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for group in groups:
        train = np.asarray([i for i, row in enumerate(rows) if row["geography_group"] != group])
        test = np.asarray([i for i, row in enumerate(rows) if row["geography_group"] == group])
        if len(train) and len(test) and len({rows[i]["label"] for i in train}) == len(LABELS):
            folds.append((train, test))
    if len(folds) < 2:
        raise ValueError("At least two leakage-safe geography folds with all classes are required")
    return folds


def _ece(y_high: np.ndarray, p_high: np.ndarray, bins: int = 10) -> float:
    total = len(y_high)
    value = 0.0
    for lower in np.linspace(0, 1, bins, endpoint=False):
        upper = lower + 1 / bins
        mask = (p_high >= lower) & (p_high < upper if upper < 1 else p_high <= upper)
        if mask.any():
            value += abs(float(y_high[mask].mean()) - float(p_high[mask].mean())) * mask.sum()
    return value / max(1, total)


def _wilson(successes: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 1.0]
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def rule_baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    predictions: list[str] = []
    for row in rows:
        features = row["features"]
        if (
            features.get("corridor_official_closure_active") is True
            or features.get("corridor_extreme_alert_active") is True
            or (features.get("hazard_intersection_fraction") or 0) >= 0.15
        ):
            predictions.append("HIGH")
        elif (features.get("max_weather_severity_ordinal") or 0) >= 2:
            predictions.append("MEDIUM")
        else:
            predictions.append("LOW")
    truth = [row["label"] for row in rows]
    return {
        "confusion_matrix": confusion_matrix(truth, predictions, labels=list(LABELS)).tolist(),
        "high_risk_recall": float(
            recall_score(truth, predictions, labels=["HIGH"], average=None)[0]
        ),
    }


def _coverage_group(row: dict[str, Any]) -> str:
    coverage = float(row["features"].get("critical_evidence_coverage") or 0)
    return "DEGRADED" if coverage < 1 else "COMPLETE"


def _evaluate(model: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    x, y = _matrix(rows)
    started = time.perf_counter()
    tracemalloc.start()
    probabilities = model.predict_proba(x)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    latency = (time.perf_counter() - started) * 1000 / max(1, len(rows))
    classes = list(model.classes_)
    predicted = np.asarray([classes[index] for index in probabilities.argmax(axis=1)])
    precision, recall, f1, support = precision_recall_fscore_support(
        y, predicted, labels=list(LABELS), zero_division=0
    )
    high_index = classes.index("HIGH")
    high_truth = (y == "HIGH").astype(int)
    high_probability = probabilities[:, high_index]
    high_total = int(high_truth.sum())
    high_hits = int(((predicted == "HIGH") & (y == "HIGH")).sum())
    y_binary = label_binarize(y, classes=list(LABELS))
    ordered_probabilities = probabilities[:, [classes.index(label) for label in LABELS]]
    threshold_curve = [
        {
            "threshold": threshold,
            "recall": float(((high_probability >= threshold) & (high_truth == 1)).sum())
            / max(1, high_total),
            "false_positive_rate": float(
                ((high_probability >= threshold) & (high_truth == 0)).sum()
            )
            / max(1, int((high_truth == 0).sum())),
        }
        for threshold in (0.1, 0.25, 0.5, 0.75, 0.9)
    ]
    return {
        "high_risk_recall": high_hits / max(1, high_total),
        "high_risk_false_negative_rate": 1 - high_hits / max(1, high_total),
        "high_risk_false_negative_confidence_interval": _wilson(high_total - high_hits, high_total),
        "per_class": {
            label: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
            }
            for i, label in enumerate(LABELS)
        },
        "roc_auc": float(roc_auc_score(y_binary, ordered_probabilities, multi_class="ovr")),
        "pr_auc": float(average_precision_score(high_truth, high_probability)),
        "brier_score": float(brier_score_loss(high_truth, high_probability)),
        "expected_calibration_error": _ece(high_truth, high_probability),
        "confusion_matrix": confusion_matrix(y, predicted, labels=list(LABELS)).tolist(),
        "inference_latency_ms": latency,
        "peak_memory_mb": peak / (1024 * 1024),
        "threshold_boundaries": threshold_curve,
    }


def derive_high_threshold(metrics: dict[str, Any], minimum_recall: float | None) -> float:
    """Select the highest boundary satisfying an explicitly approved recall objective."""
    if minimum_recall is None:
        raise ValueError("APPROVED_HIGH_RECALL_OBJECTIVE_REQUIRED")
    eligible = [
        item for item in metrics["threshold_boundaries"] if float(item["recall"]) >= minimum_recall
    ]
    if not eligible:
        raise ValueError("NO_THRESHOLD_SATISFIES_APPROVED_OBJECTIVE")
    return float(max(eligible, key=lambda item: float(item["threshold"]))["threshold"])


def train(dataset_dir: Path, output_dir: Path, version: str = "1.0.0") -> TrainingResult:
    rows = json.loads((dataset_dir / "dataset_rows.json").read_text(encoding="utf-8"))
    dataset_manifest = json.loads(
        (dataset_dir / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    if not dataset_manifest["split"]["leakage_check_passed"]:
        raise ValueError("Dataset leakage check must pass before training")
    x, y = _matrix(rows)
    numeric = list(range(len(FEATURE_NAMES)))
    preprocessor = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
                ),
                numeric,
            )
        ],
        remainder="drop",
    )
    estimator = Pipeline(
        [
            ("preprocessor", preprocessor),
            (
                "classifier",
                LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42),
            ),
        ]
    )
    model = CalibratedClassifierCV(estimator, method="sigmoid", cv=_folds(rows), ensemble=False)
    model.fit(x, y)
    metrics = _evaluate(model, rows)
    metrics["rule_baseline"] = rule_baseline(rows)
    metrics["subgroups"] = {
        field: {
            value: _evaluate(model, [row for row in rows if str(row[field]) == value])
            for value in sorted({str(row[field]) for row in rows})
            if len({row["label"] for row in rows if str(row[field]) == value}) == len(LABELS)
        }
        for field in ("geography_group", "season", "hazard_type", "travel_mode")
    }
    metrics["subgroups"]["degraded_coverage"] = {
        value: _evaluate(
            model,
            [row for row in rows if _coverage_group(row) == value],
        )
        for value in ("DEGRADED", "COMPLETE")
        if len({row["label"] for row in rows if _coverage_group(row) == value}) == len(LABELS)
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"route-risk-baseline-{version}.joblib"
    joblib.dump(
        {
            "model": model,
            "feature_names": FEATURE_NAMES,
            "feature_schema_version": "1.0.0",
            "reason_codes": REASON_BY_FEATURE,
        },
        artifact,
    )
    checksum = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = output_dir / "model_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "route-risk-baseline",
                "version": version,
                "stage": "CANDIDATE",
                "dataset_checksum": dataset_manifest["content_checksum"],
                "artifact_checksum": checksum,
                "feature_schema_version": "1.0.0",
                "metrics": metrics,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    model_card = output_dir / "model_card.md"
    model_card.write_text(
        (
            f"# Route Risk Baseline {version}\n\n"
            "Status: CANDIDATE\n\n"
            f"Dataset: `{dataset_manifest['content_checksum']}`\n\n"
            f"Artifact: `{checksum}`\n\n"
            "The model reports associations, not causal effects. Promotion remains "
            "fail-closed until governance approval and signing.\n"
        ),
        encoding="utf-8",
    )
    return TrainingResult(artifact, checksum, metrics, model_card, manifest)
