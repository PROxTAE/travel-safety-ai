"""Idempotent maintenance commands for the integration store.

    python -m app.cli.operations backfill --kind weather --input records.jsonl
    python -m app.cli.operations purge-quarantine [--days 30]
    python -m app.cli.operations rebuild --snapshot-id <uuid>

Every command is safe to rerun: backfill skips stored records and re-quarantines
nothing, purge removes only expired rows, and rebuild never writes.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.canonical import RECORD_MODELS
from app.domain.snapshot import SnapshotCreateRequest
from app.pipeline.build import build_route_snapshot, evidence_from_request
from app.repositories.canonical_repo import CanonicalRepository
from app.repositories.db import build_engine, build_session_factory, unit_of_work
from app.repositories.models import Snapshot
from app.repositories.quarantine_repo import QuarantineRepository
from app.settings import Settings, get_settings

EXIT_DRIFT = 3
EXIT_NOT_REBUILDABLE = 4


@dataclass(frozen=True)
class BackfillReport:
    stored: int
    quarantined: int


async def backfill(engine: AsyncEngine, kind: str, lines: list[str]) -> BackfillReport:
    """Ingest canonical records; the unique key makes a second run a no-op."""
    stored = quarantined = 0
    async with unit_of_work(build_session_factory(engine)) as session:
        repository = CanonicalRepository(session)
        for line in lines:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                raw = {"unparseable_line": line}
            if await repository.ingest(kind, raw) is None:
                quarantined += 1
            else:
                stored += 1
    return BackfillReport(stored, quarantined)


async def purge_quarantine(engine: AsyncEngine, days: int) -> int:
    async with unit_of_work(build_session_factory(engine)) as session:
        return await QuarantineRepository(session).purge_before(days=days)


async def rebuild(engine: AsyncEngine, snapshot_id: UUID, settings: Settings) -> str:
    """Re-run the pipeline on the stored request and compare content hashes."""
    factory = build_session_factory(engine)
    async with factory() as session:
        row = await session.get(Snapshot, snapshot_id)
        if row is None:
            return "missing"
        if row.request_json is None:
            return "not_rebuildable"
        body = SnapshotCreateRequest.model_validate(row.request_json)
        stored_hash = row.content_hash
        rebuilt = await build_route_snapshot(
            session,
            snapshot_id=row.id,
            request_id=body.request_id,
            trip_id=body.trip_id,
            supersedes_snapshot_id=body.supersedes_snapshot_id,
            travel_window=body.travel_window,
            recommendation_at=body.recommendation_at,
            evidence=evidence_from_request(body),
            settings=settings,
            created_at=row.created_at,
        )
        # Rebuilding only reads; nothing from this session is kept.
        await session.rollback()
    return "reproducible" if rebuilt.content_hash == stored_hash else "drift"


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        if args.command == "backfill":
            lines = Path(args.input).read_text(encoding="utf-8").splitlines()
            report = await backfill(engine, args.kind, lines)
            print(f"stored={report.stored} quarantined={report.quarantined}")
            return 0
        if args.command == "purge-quarantine":
            removed = await purge_quarantine(
                engine, args.days or settings.quarantine_retention_days
            )
            print(f"removed={removed}")
            return 0
        outcome = await rebuild(engine, args.snapshot_id, settings)
        print(outcome)
        codes = {"reproducible": 0, "drift": EXIT_DRIFT, "not_rebuildable": EXIT_NOT_REBUILDABLE}
        return codes.get(outcome, 1)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Integration store maintenance.")
    commands = parser.add_subparsers(dest="command", required=True)
    fill = commands.add_parser("backfill", help="ingest canonical records from JSON lines")
    fill.add_argument("--kind", required=True, choices=sorted(RECORD_MODELS))
    fill.add_argument("--input", required=True)
    purge = commands.add_parser("purge-quarantine", help="delete expired quarantine rows")
    purge.add_argument("--days", type=int, default=None)
    again = commands.add_parser("rebuild", help="verify a snapshot can be reproduced")
    again.add_argument("--snapshot-id", required=True, type=UUID)
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
