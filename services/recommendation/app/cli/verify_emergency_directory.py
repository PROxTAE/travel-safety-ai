from __future__ import annotations

import argparse
import asyncio
import sys

from app.database import get_session_factory
from app.directory.ingest import ingest_emergency_directory
from app.directory.validate import validate_sources_manifest
from app.settings import get_settings


async def run_verify(manifest_path: str, sync_db: bool = False) -> int:
    print(f"Verifying emergency directory manifest: {manifest_path}")
    try:
        entries = validate_sources_manifest(manifest_path)
        print(f" Successfully validated {len(entries)} verified emergency contact entries.")
        for e in entries:
            print(
                f"  - [{e.country_code}] {e.service_type}: {e.phone} "
                f"({e.authority}, reviewed until {e.review_due_at})"
            )

        if sync_db:
            factory = get_session_factory()
            async with factory() as session:
                count = await ingest_emergency_directory(session, manifest_path)
                print(f" Ingested/synced {count} entries to PostgreSQL 'emergency_contacts' table.")
        return 0
    except Exception as e:
        print(f" Verification failed: {e}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and ingest official emergency directory sources."
    )
    parser.add_argument(
        "--path",
        default=get_settings().EMERGENCY_DIRECTORY_PATH,
        help="Path to sources.yaml manifest",
    )
    parser.add_argument(
        "--sync-db",
        action="store_true",
        help="Sync validated entries into the database",
    )
    args = parser.parse_args()
    code = asyncio.run(run_verify(args.path, args.sync_db))
    sys.exit(code)


if __name__ == "__main__":
    main()
