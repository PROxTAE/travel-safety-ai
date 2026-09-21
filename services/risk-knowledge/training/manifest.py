"""Dataset manifest builder and JSON Schema validator for Module 06.

Ensures strict compliance with dataset_manifest.schema.json:
- Validates all required properties and formats
- Computes canonical content checksum
- Validates split structure and authority constraints
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import validate

SCHEMA_PATH = Path(__file__).resolve().parent / "dataset_manifest.schema.json"


def load_manifest_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def compute_dataset_content_checksum(rows: list[dict[str, Any]]) -> str:
    """Compute deterministic SHA-256 checksum over the serialized canonical rows."""
    canonical_repr = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_dataset_manifest(
    dataset_id: str,
    prediction_cutoff: str,
    label_method: str,
    sources: list[dict[str, Any]],
    query_windows: list[dict[str, Any]],
    split_info: dict[str, Any],
    row_count: int,
    class_distribution: dict[str, int],
    content_checksum: str,
    license_review: str = "APPROVED",
    created_by: str = "module-06-risk-knowledge",
) -> dict[str, Any]:
    """Construct a dataset manifest object conforming to dataset_manifest.schema.json."""
    manifest = {
        "manifest_version": "1.0.0",
        "dataset_id": dataset_id,
        "created_at": datetime.now(UTC).isoformat(),
        "prediction_cutoff": prediction_cutoff,
        "feature_schema_version": "1.0.0",
        "label_method": label_method,
        "sources": sources,
        "query_windows": query_windows,
        "split": split_info,
        "row_count": row_count,
        "class_distribution": class_distribution,
        "content_checksum": content_checksum,
        "license_review": license_review,
        "created_by": created_by,
    }

    # Validate against schema
    schema = load_manifest_schema()
    validate(instance=manifest, schema=schema)
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Validate a dictionary against dataset manifest schema, raising on error."""
    schema = load_manifest_schema()
    validate(instance=manifest, schema=schema)
