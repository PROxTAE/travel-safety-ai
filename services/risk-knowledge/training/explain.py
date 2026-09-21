"""Exact additive logit attributions for the calibrated linear baseline."""

from __future__ import annotations

from typing import Any

import numpy as np


def linear_shap_values(
    bundle: dict[str, Any], vector: list[object], label: str
) -> dict[str, float]:
    """Return linear SHAP-equivalent contributions after fitted preprocessing.

    For a linear logit model, coefficient * transformed feature is the exact additive
    contribution around the zero baseline. Calibration is intentionally excluded because
    explanations describe the classifier logit rather than claim causal probability effects.
    """
    model = bundle["model"]
    calibrated = model.calibrated_classifiers_[0]
    pipeline = calibrated.estimator
    transformed = pipeline.named_steps["preprocessor"].transform(np.asarray([vector], dtype=object))
    classifier = pipeline.named_steps["classifier"]
    class_index = list(classifier.classes_).index(label)
    contributions = transformed[0] * classifier.coef_[class_index]
    names = list(bundle["feature_names"])
    imputer = (
        pipeline.named_steps["preprocessor"].named_transformers_["numeric"].named_steps["imputer"]
    )
    retained_names = [
        name
        for name, statistic in zip(names, imputer.statistics_, strict=True)
        if not np.isnan(statistic)
    ]
    return {name: float(contributions[index]) for index, name in enumerate(retained_names)}


def validate_reason_mapping(
    contributions: dict[str, float], reason_codes: dict[str, str], *, limit: int = 5
) -> list[str]:
    ordered = sorted(contributions, key=lambda name: abs(contributions[name]), reverse=True)
    missing = [name for name in ordered[:limit] if name not in reason_codes]
    if missing:
        raise ValueError("UNMAPPED_IMPORTANT_FEATURE:" + ",".join(missing))
    return [reason_codes[name] for name in ordered[:limit]]
