"""Phase 8 release evidence validation without hidden provider substitutes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def verify_release(model_manifest: Path, model_card: Path, evaluation: Path) -> dict[str, Any]:
    manifest = json.loads(model_manifest.read_text(encoding="utf-8"))
    evaluation_data = json.loads(evaluation.read_text(encoding="utf-8"))
    card = model_card.read_text(encoding="utf-8")
    failures: list[str] = []
    if manifest.get("stage") != "ACTIVE":
        failures.append("MODEL_NOT_ACTIVE")
    if "associations, not causal" not in card:
        failures.append("MODEL_CARD_CAUSALITY_WARNING_MISSING")
    if not evaluation_data.get("golden_cases_passed", False):
        failures.append("GOLDEN_CASES_NOT_PASSED")
    checksum = "sha256:" + hashlib.sha256(model_manifest.read_bytes()).hexdigest()
    return {"ready": not failures, "failures": failures, "release_manifest_checksum": checksum}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--model-card", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    args = parser.parse_args()
    result = verify_release(args.model_manifest, args.model_card, args.evaluation)
    print(json.dumps(result, sort_keys=True))
    if not result["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
