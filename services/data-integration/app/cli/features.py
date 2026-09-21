"""Offline feature batch for the module 06 training pipeline.

Reads one SnapshotCreateRequest per JSON line and writes one feature row per
line, using the same code path as POST /internal/v1/snapshots. Any invalid line
stops the batch with its line number and no output file, so a training set is
never silently missing rows.

    docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration \
        python -m app.cli.features --input requests.jsonl --output features.jsonl
"""

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.domain.snapshot import SnapshotCreateRequest
from app.pipeline.build import compute_route_features, evidence_from_request
from app.settings import Settings, get_settings


class BatchInputError(ValueError):
    """A request line is not valid; the message names the line, never its values."""


def feature_row(body: SnapshotCreateRequest, settings: Settings) -> dict[str, Any]:
    _, _, vector = compute_route_features(
        evidence_from_request(body),
        travel_window=body.travel_window,
        recommendation_at=body.recommendation_at,
        settings=settings,
    )
    return {
        "request_id": str(body.request_id),
        "trip_id": str(body.trip_id),
        "route_id": body.route.route_id,
        "recommendation_at": body.recommendation_at.isoformat(),
        "feature_schema_version": vector.schema_version,
        "features": vector.values,
        "null_features": list(vector.null_features),
    }


def run(lines: Iterable[str], settings: Settings) -> list[str]:
    rows: list[str] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            body = SnapshotCreateRequest.model_validate_json(line)
            row = feature_row(body, settings)
        except (ValidationError, ValueError) as failure:
            raise BatchInputError(f"line {number}: request cannot produce features") from failure
        rows.append(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return rows


def _write(rows: list[str], output: str) -> None:
    text = "".join(row + "\n" for row in rows)
    if output == "-":
        sys.stdout.write(text)
        return
    target = Path(output)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.replace(temporary, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline feature batch for module 06 training.")
    parser.add_argument("--input", required=True, help="JSON lines file, or - for stdin")
    parser.add_argument("--output", required=True, help="JSON lines file, or - for stdout")
    args = parser.parse_args(argv)
    if args.input == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = Path(args.input).read_text(encoding="utf-8").splitlines()
    try:
        rows = run(lines, get_settings())
    except BatchInputError as failure:
        print(str(failure), file=sys.stderr)
        return 2
    _write(rows, args.output)
    print(f"{len(rows)} feature rows written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
