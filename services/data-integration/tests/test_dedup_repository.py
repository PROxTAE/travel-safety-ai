"""Concurrency checks on isolated PostgreSQL using captured USGS event metadata."""

import asyncio
import copy
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from test_dedup import captured_event

from app.domain.errors import SnapshotConflictError
from app.pipeline.dedup import candidate_links, resolve_field
from app.repositories.dedup_repo import DedupRepository
from app.repositories.models import CanonicalRecord, DedupCluster
from app.repositories.snapshot_repo import canonical_hash


async def test_concurrent_cluster_upserts_keep_one_row_and_all_evidence(
    isolated_database: str,
) -> None:
    engine = create_async_engine(isolated_database)
    try:
        official = captured_event()
        community = copy.deepcopy(official)
        community["event_id"] = "community:event"
        community["cross_reference_ids"] = [official["event_id"]]
        community["severity"] = "MINOR"
        community["official"] = False
        community["source"] = {
            **community["source"],
            "source_id": "community:event",
            "provider": "community",
            "provider_record_id": "event",
            "authority": "COMMUNITY",
        }
        official["severity"] = "SEVERE"
        records = [official, community]
        members = [
            CanonicalRecord(
                id=uuid4(),
                record_type="disaster",
                source_id=record["source"]["source_id"],
                content_hash=canonical_hash(record),
                schema_version="1.0.0",
                transform_version="1.0.0",
                payload_json=record,
                lineage_json={},
                fetched_at=datetime.fromisoformat(
                    record["source"]["fetched_at"].replace("Z", "+00:00")
                ),
            )
            for record in records
        ]
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(members)
            await session.commit()
        links = candidate_links(records, max_distance_m=0, max_time_seconds=0)
        resolution = resolve_field(records, "severity")

        async def write_once() -> str:
            async with AsyncSession(engine) as session:
                row = await DedupRepository(session).create(
                    record_type="disaster",
                    members=members,
                    matches=links,
                    conflicts={"severity": resolution},
                )
                result = str(row.id)
                await session.commit()
                return result

        first_id, second_id = await asyncio.gather(write_once(), write_once())
        assert first_id == second_id
        async with AsyncSession(engine) as session:
            assert await session.scalar(select(func.count()).select_from(DedupCluster)) == 1
            row = (await session.execute(select(DedupCluster))).scalar_one()
            assert len(row.members_json) == 2
            assert row.conflicts_json["severity"]["status"] == "CONFLICTING"
            assert len(row.conflicts_json["severity"]["evidence"]) == 2
            with pytest.raises(SnapshotConflictError):
                await DedupRepository(session).create(
                    record_type="disaster",
                    members=members,
                    matches=[],
                    conflicts={},
                )
    finally:
        await engine.dispose()
