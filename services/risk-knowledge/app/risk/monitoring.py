"""Privacy-safe model drift aggregates; never performs automatic retraining."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class DriftWindow:
    version: str
    predictions: Counter[str] = field(default_factory=Counter)
    feature_missing: Counter[str] = field(default_factory=Counter)
    dimensions: Counter[str] = field(default_factory=Counter)
    feedback: Counter[str] = field(default_factory=Counter)

    def observe(
        self,
        risk_level: str,
        missing_features: list[str],
        *,
        location: str = "UNKNOWN",
        season: str = "UNKNOWN",
        hazard: str = "UNKNOWN",
    ) -> None:
        self.predictions[risk_level] += 1
        self.feature_missing.update(missing_features)
        self.dimensions[f"location:{location}"] += 1
        self.dimensions[f"season:{season}"] += 1
        self.dimensions[f"hazard:{hazard}"] += 1

    def observe_feedback(self, predicted: str, observed: str) -> None:
        self.feedback[f"{predicted}->{observed}"] += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "version": self.version,
            "predictions": dict(self.predictions),
            "feature_missing": dict(self.feature_missing),
            "dimensions": dict(self.dimensions),
            "feedback": dict(self.feedback),
            "high_risk_recall_proxy": self._high_recall_proxy(),
            "automatic_retraining": False,
        }

    def _high_recall_proxy(self) -> float | None:
        observed_high = sum(
            count for transition, count in self.feedback.items() if transition.endswith("->HIGH")
        )
        if observed_high == 0:
            return None
        true_high = self.feedback.get("HIGH->HIGH", 0)
        return true_high / observed_high
