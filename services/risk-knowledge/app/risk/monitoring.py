"""Privacy-safe model drift aggregates; never performs automatic retraining."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class DriftWindow:
    version: str
    predictions: Counter[str] = field(default_factory=Counter)
    feature_missing: Counter[str] = field(default_factory=Counter)

    def observe(self, risk_level: str, missing_features: list[str]) -> None:
        self.predictions[risk_level] += 1
        self.feature_missing.update(missing_features)

    def snapshot(self) -> dict[str, object]:
        return {
            "version": self.version,
            "predictions": dict(self.predictions),
            "feature_missing": dict(self.feature_missing),
            "automatic_retraining": False,
        }
