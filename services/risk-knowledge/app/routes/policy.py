from __future__ import annotations

from pathlib import Path

import yaml


def load_approved_severity_weights(path: Path) -> tuple[str, dict[str, float] | None]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    version = str(payload["policy_version"])
    if payload.get("status") not in {"APPROVED", "ACTIVE"}:
        return version, None
    weights = payload["exposure_formula"]["coefficients"].get("severity_weights")
    if not isinstance(weights, dict) or not weights:
        return version, None
    return version, {str(key): float(value) for key, value in weights.items()}
