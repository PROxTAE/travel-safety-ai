"""Backup export and restore sample utility for Smart Travel API.

Provides operational procedures for:
1. Exporting data snapshots from `identity` and `travel` tables (with integrity hashing).
2. Validating snapshot integrity and schema compliance.
3. Restoring records into target database environments.

Usage:
  # Export snapshot to file
  uv run python scripts/backup_restore_sample.py export --output snapshot.json

  # Validate existing snapshot
  uv run python scripts/backup_restore_sample.py validate --input snapshot.json

  # Restore snapshot into database
  uv run python scripts/backup_restore_sample.py restore --input snapshot.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.settings import get_settings


def calculate_checksum(data: Any) -> str:
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def export_snapshot(engine: Any, output_path: Path) -> dict[str, Any]:
    """Export non-credential domain data from identity and travel schemas."""
    snapshot: dict[str, Any] = {
        "metadata": {
            "version": "1.0.0",
            "exported_at": datetime.now(UTC).isoformat(),
            "schemas": ["identity", "travel"],
        },
        "tables": {},
    }

    with engine.connect() as conn:
        # 1. Export identity.user_profiles
        profiles = [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT id, subject_id, locale, timezone, home_country_code, "
                    "disabled_at, created_at, updated_at FROM identity.user_profiles"
                )
            ).fetchall()
        ]
        snapshot["tables"]["identity.user_profiles"] = profiles

        # 2. Export identity.consents
        consents = [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT id, user_id, type, granted, policy_version, "
                    "granted_at, revoked_at, expires_at FROM identity.consents"
                )
            ).fetchall()
        ]
        snapshot["tables"]["identity.consents"] = consents

        # 3. Export travel.trips
        trips = [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT id, user_id, revision, title, origin, destination, "
                    "departure_time, return_time, timezone, travel_modes, status, "
                    "created_at, updated_at, deleted_at FROM travel.trips"
                )
            ).fetchall()
        ]
        snapshot["tables"]["travel.trips"] = trips

    snapshot["metadata"]["checksum"] = calculate_checksum(snapshot["tables"])

    output_path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    return snapshot


def validate_snapshot(input_path: Path) -> bool:
    """Validate snapshot structure and checksum."""
    if not input_path.exists():
        print(f"Error: Snapshot file not found: {input_path}", file=sys.stderr)
        return False

    data = json.loads(input_path.read_text(encoding="utf-8"))
    meta = data.get("metadata", {})
    tables = data.get("tables", {})

    expected_checksum = meta.get("checksum")
    actual_checksum = calculate_checksum(tables)

    if expected_checksum != actual_checksum:
        print(
            f"Checksum mismatch! Expected: {expected_checksum}, Actual: {actual_checksum}",
            file=sys.stderr,
        )
        return False

    print(f"Snapshot valid. Tables included: {list(tables.keys())}")
    for tbl, rows in tables.items():
        print(f"  - {tbl}: {len(rows)} records")
    return True


def restore_snapshot(engine: Any, input_path: Path) -> int:
    """Restore records from snapshot into database."""
    if not validate_snapshot(input_path):
        raise ValueError("Invalid snapshot file")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    tables = data.get("tables", {})
    restored_count = 0

    with engine.begin() as conn:
        for profile in tables.get("identity.user_profiles", []):
            conn.execute(
                text(
                    "INSERT INTO identity.user_profiles "
                    "(id, subject_id, locale, timezone, home_country_code, disabled_at, "
                    "created_at, updated_at) "
                    "VALUES (:id, :subject_id, :locale, :timezone, :home_country_code, "
                    ":disabled_at, :created_at, :updated_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                profile,
            )
            restored_count += 1

        for consent in tables.get("identity.consents", []):
            conn.execute(
                text(
                    "INSERT INTO identity.consents "
                    "(id, user_id, type, granted, policy_version, granted_at, revoked_at, "
                    "expires_at) "
                    "VALUES (:id, :user_id, :type, :granted, :policy_version, :granted_at, "
                    ":revoked_at, :expires_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                consent,
            )
            restored_count += 1

        for trip in tables.get("travel.trips", []):
            # Ensure JSON fields are converted properly
            origin = trip["origin"]
            dest = trip["destination"]
            modes = trip["travel_modes"]
            origin_val = json.dumps(origin) if isinstance(origin, dict | list) else origin
            dest_val = json.dumps(dest) if isinstance(dest, dict | list) else dest
            modes_val = json.dumps(modes) if isinstance(modes, list) else modes

            conn.execute(
                text(
                    "INSERT INTO travel.trips "
                    "(id, user_id, revision, title, origin, destination, departure_time, "
                    "return_time, timezone, travel_modes, status, created_at, updated_at, "
                    "deleted_at) "
                    "VALUES (:id, :user_id, :revision, :title, :origin, :destination, "
                    ":departure_time, :return_time, :timezone, :travel_modes, :status, "
                    ":created_at, :updated_at, :deleted_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    **trip,
                    "origin": origin_val,
                    "destination": dest_val,
                    "travel_modes": modes_val,
                },
            )
            restored_count += 1

    return restored_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup and Restore Sample Utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_p = subparsers.add_parser("export")
    export_p.add_argument("--output", type=Path, default=Path("backup_snapshot.json"))

    validate_p = subparsers.add_parser("validate")
    validate_p.add_argument("--input", type=Path, default=Path("backup_snapshot.json"))

    restore_p = subparsers.add_parser("restore")
    restore_p.add_argument("--input", type=Path, default=Path("backup_snapshot.json"))

    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.sync_database_url)

    if args.command == "export":
        snap = export_snapshot(engine, args.output)
        print(f"Exported snapshot with checksum {snap['metadata']['checksum']} to {args.output}")
    elif args.command == "validate":
        if validate_snapshot(args.input):
            print("Validation successful.")
        else:
            sys.exit(1)
    elif args.command == "restore":
        count = restore_snapshot(engine, args.input)
        print(f"Restored {count} records from {args.input}")


if __name__ == "__main__":
    main()
