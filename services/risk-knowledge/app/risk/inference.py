"""Verified local model inference with strict schema and quality guards."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import joblib

from app.contracts import (
    DataQuality,
    DataStatus,
    IntegratedTravelContext,
    ModelReference,
    RiskAssessment,
    RiskLevel,
)
from training.features import CRITICAL_FEATURES, FEATURE_NAMES


class ModelInputRejected(ValueError):
    pass


class RiskPredictor:
    def __init__(self, path: Path, model: ModelReference) -> None:
        bundle = joblib.load(path)
        if (
            tuple(bundle["feature_names"]) != FEATURE_NAMES
            or bundle["feature_schema_version"] != "1.0.0"
        ):
            raise ModelInputRejected("FEATURE_SCHEMA_MISMATCH")
        self.estimator = bundle["model"]
        self.reasons: dict[str, str] = bundle["reason_codes"]
        self.reference = model

    def assess(
        self, snapshot: IntegratedTravelContext, route_ids: list[UUID]
    ) -> list[RiskAssessment]:
        if snapshot.feature_schema_version != "1.0.0":
            raise ModelInputRejected("FEATURE_SCHEMA_UNSUPPORTED")
        missing = sorted(name for name in CRITICAL_FEATURES if snapshot.features.get(name) is None)
        if missing:
            raise ModelInputRejected("MISSING_CRITICAL_EVIDENCE:" + ",".join(missing))
        by_id = {route.route_id: route for route in snapshot.route_candidates}
        results: list[RiskAssessment] = []
        for route_id in route_ids:
            route = by_id[route_id]
            values = dict(snapshot.features)
            values.update(
                {
                    "route_distance_m": route.distance_m,
                    "route_duration_seconds": route.duration_seconds,
                    "route_transfer_count": route.transfers,
                }
            )
            vector = [[values.get(name) for name in FEATURE_NAMES]]
            probabilities = self.estimator.predict_proba(vector)[0]
            classes = list(self.estimator.classes_)
            predicted = str(classes[int(probabilities.argmax())])
            probability_high = float(probabilities[classes.index("HIGH")])
            confidence = float(max(probabilities))
            reason_codes = [
                self.reasons[name]
                for name in FEATURE_NAMES
                if name in self.reasons and values.get(name) not in (None, False, 0, 0.0)
            ]
            results.append(
                RiskAssessment(
                    assessment_id=uuid4(),
                    snapshot_id=snapshot.snapshot_id,
                    route_id=cast(UUID, route.route_id),
                    score=probability_high,
                    probability_high=probability_high,
                    risk_level=RiskLevel(predicted),
                    uncertainty=1.0 - confidence,
                    reason_codes=list(dict.fromkeys(reason_codes))[:5],
                    safety_overrides=[],
                    model=self.reference,
                    quality=DataQuality(
                        status=DataStatus.FRESH,
                        score=snapshot.quality_summary.score,
                        score_version=snapshot.quality_summary.score_version,
                        flags=snapshot.quality_summary.flags,
                        coverage=snapshot.quality_summary.coverage,
                        completeness=snapshot.quality_summary.completeness,
                        freshness_seconds=snapshot.quality_summary.freshness_seconds,
                        conflicts=snapshot.quality_summary.conflicts,
                        notes=["Calibrated local baseline; associations are not causal claims."],
                    ),
                    created_at=datetime.now(UTC),
                )
            )
        return results
