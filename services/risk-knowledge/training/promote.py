"""Fail-closed model promotion gates for Phase 3/8."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def evaluate_promotion(
    manifest: dict[str, Any],
    acceptance: dict[str, Any],
    *,
    approver: str | None,
    signature_path: Path | None,
    target_stage: str,
) -> list[str]:
    failures: list[str] = []
    current_stage = str(manifest.get("stage", "CANDIDATE"))
    if target_stage not in {"APPROVED", "ACTIVE"}:
        failures.append("INVALID_PROMOTION_TARGET")
    if target_stage == "ACTIVE" and current_stage != "APPROVED":
        failures.append("MODEL_MUST_BE_APPROVED_BEFORE_ACTIVE")
    if acceptance.get("status") not in {"APPROVED", "ACTIVE"}:
        failures.append("MODEL_ACCEPTANCE_NOT_APPROVED")
    thresholds = acceptance["thresholds"]
    for name in (
        "high_risk_recall_min",
        "high_risk_false_negative_rate_max",
        "expected_calibration_error_max",
    ):
        if thresholds.get(name) is None:
            failures.append(f"NULL_SAFETY_THRESHOLD:{name}")
    if not approver:
        failures.append("APPROVER_REQUIRED")
    if signature_path is None or not signature_path.is_file():
        failures.append("ARTIFACT_SIGNATURE_REQUIRED")
    metrics = manifest["metrics"]
    if (
        thresholds.get("high_risk_recall_min") is not None
        and metrics["high_risk_recall"] < thresholds["high_risk_recall_min"]
    ):
        failures.append("HIGH_RECALL_BELOW_GATE")
    if (
        thresholds.get("high_risk_false_negative_rate_max") is not None
        and metrics["high_risk_false_negative_rate"]
        > thresholds["high_risk_false_negative_rate_max"]
    ):
        failures.append("FALSE_NEGATIVE_RATE_ABOVE_GATE")
    if (
        thresholds.get("expected_calibration_error_max") is not None
        and metrics["expected_calibration_error"] > thresholds["expected_calibration_error_max"]
    ):
        failures.append("CALIBRATION_ABOVE_GATE")
    return failures


def promote(
    manifest_path: Path,
    acceptance_path: Path,
    output_path: Path,
    *,
    approver: str | None = None,
    signature_path: Path | None = None,
    target_stage: str = "APPROVED",
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acceptance = yaml.safe_load(acceptance_path.read_text(encoding="utf-8"))
    failures = evaluate_promotion(
        manifest,
        acceptance,
        approver=approver,
        signature_path=signature_path,
        target_stage=target_stage,
    )
    record = {
        **manifest,
        "stage": str(manifest.get("stage", "CANDIDATE")) if failures else target_stage,
        "approved_by": approver if not failures else None,
        "approved_at": datetime.now(UTC).isoformat() if not failures else None,
        "promotion_failures": failures,
    }
    output_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approver")
    parser.add_argument("--signature", type=Path)
    parser.add_argument("--target-stage", choices=("APPROVED", "ACTIVE"), default="APPROVED")
    args = parser.parse_args()
    record = promote(
        args.manifest,
        args.acceptance,
        args.output,
        approver=args.approver,
        signature_path=args.signature,
        target_stage=args.target_stage,
    )
    print(json.dumps(record, sort_keys=True))
    if record["promotion_failures"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
