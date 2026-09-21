"""Quarantine policy and immutable snapshot idempotency against PostgreSQL."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from app.domain.errors import SnapshotConflictError
from app.repositories.db import build_engine, build_session_factory, unit_of_work
from app.repositories.models import Quarantine, Snapshot
from app.repositories.quarantine_repo import QuarantineRepository
from app.repositories.snapshot_repo import SnapshotRepository


@pytest.mark.asyncio
async def test_quarantine_does_not_store_raw_without_permission(isolated_database: str) -> None:
    engine = build_engine(isolated_database)
    try:
        async with unit_of_work(build_session_factory(engine)) as session:
            repo = QuarantineRepository(session)
            row = await repo.record(
                source_hash="sha256:" + "a" * 64,
                error_code="INVALID_GEOMETRY",
                field_path="geometry",
                raw_content={"private": "value"},
            )
            assert row.raw_content is None
            assert row.status == "OPEN"
            assert await repo.purge_before(days=30) == 0
            assert (
                await session.execute(select(Quarantine).where(Quarantine.id == row.id))
            ).scalar_one()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_quarantine_retention_removes_only_expired_rows(isolated_database: str) -> None:
    engine = build_engine(isolated_database)
    try:
        async with unit_of_work(build_session_factory(engine)) as session:
            repo = QuarantineRepository(session)
            old = await repo.record(source_hash="sha256:" + "c" * 64, error_code="INVALID_TIME")
            recent = await repo.record(source_hash="sha256:" + "d" * 64, error_code="INVALID_TIME")
            await session.execute(
                update(Quarantine)
                .where(Quarantine.id == old.id)
                .values(created_at=datetime.now(UTC) - timedelta(days=40))
            )
            assert await repo.purge_before(days=30) == 1
            assert await session.get(Quarantine, old.id) is None
            assert await session.get(Quarantine, recent.id) is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_idempotency_and_conflict(isolated_database: str) -> None:
    engine = build_engine(isolated_database)
    request_id = uuid4()
    key = "sha256:" + "b" * 64
    try:
        factory = build_session_factory(engine)
        async with unit_of_work(factory) as session:
            first = await SnapshotRepository(session).create(
                request_id=request_id,
                input_content_hash=key,
                schema_version="1.0.0",
                evidence={"source_ids": ["provider-event"]},
            )
            first_id = first.id
        async with unit_of_work(factory) as session:
            repo = SnapshotRepository(session)
            same = await repo.create(
                request_id=request_id,
                input_content_hash=key,
                schema_version="1.0.0",
                evidence={"source_ids": ["provider-event"]},
            )
            assert same.id == first_id
            with pytest.raises(SnapshotConflictError):
                await repo.create(
                    request_id=request_id,
                    input_content_hash=key,
                    schema_version="1.0.0",
                    evidence={"source_ids": ["different"]},
                )
        with pytest.raises(DBAPIError):
            async with unit_of_work(factory) as session:
                await session.execute(
                    update(Snapshot).where(Snapshot.id == first_id).values(evidence_json={})
                )
    finally:
        await engine.dispose()
