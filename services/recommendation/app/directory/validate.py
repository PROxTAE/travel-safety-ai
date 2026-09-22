from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.domain.contacts import EmergencyContactEntry


def compute_entry_checksum(entry: dict[str, Any]) -> str:
    raw = (
        f"{entry.get('country_code')}:{entry.get('subdivision')}:{entry.get('service_type')}:"
        f"{entry.get('phone')}:{entry.get('authority')}:{entry.get('effective_at')}:"
        f"{entry.get('source_url')}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def validate_sources_manifest(file_path: str | Path) -> list[EmergencyContactEntry]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Emergency sources manifest not found at {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "entries" not in data:
        raise ValueError("Invalid emergency sources manifest: missing 'entries' list")

    entries: list[EmergencyContactEntry] = []

    for idx, raw_entry in enumerate(data["entries"]):
        try:
            # Parse dates if string
            for dt_field in ("effective_at", "verified_at", "review_due_at"):
                val = raw_entry.get(dt_field)
                if isinstance(val, str):
                    raw_entry[dt_field] = datetime.fromisoformat(val.replace("Z", "+00:00"))

            entry = EmergencyContactEntry(**raw_entry)
            # Verify authority is recognized
            if entry.authority not in ("OFFICIAL", "INTERGOVERNMENTAL", "LICENSED_PROVIDER"):
                msg = f"Entry {idx} authority '{entry.authority}' is not an approved authority"
                raise ValueError(msg)

            entries.append(entry)
        except (ValidationError, ValueError) as e:
            raise ValueError(
                f"Validation error in entry {idx} ({raw_entry.get('service_type', 'unknown')}): {e}"
            ) from e

    return entries
