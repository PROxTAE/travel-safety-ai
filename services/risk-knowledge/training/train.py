"""CLI for the Phase 3 calibrated baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.baseline import train


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", default="1.0.0")
    args = parser.parse_args()
    result = train(args.dataset_dir, args.output_dir, args.version)
    print(
        json.dumps(
            {
                "artifact": str(result.artifact),
                "checksum": result.checksum,
                "manifest": str(result.manifest),
                "model_card": str(result.model_card),
                "metrics": result.metrics,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
