from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.db import Database
from app.knowledge.qdrant import QdrantAliasStatus
from app.models import KnowledgeCollectionVersion, ModelVersion
from app.repositories.assessments import (
    save_fallback_assessments,
    save_fallback_route_evaluations,
)
from app.repositories.registry import (
    ActiveCollection,
    ActiveModel,
    get_active_collection,
    get_active_model,
    get_approved_collection,
    mark_collection_active,
    register_draft_collection,
)
from app.risk.artifact_loader import ArtifactUnavailable
from app.risk.fallback import assess_with_conservative_fallback
from app.runtime import KnowledgeRuntimeStatus, ModelRuntimeStatus, RuntimeState
from app.settings import Settings
from app.timeouts import hard_timeout

MODEL_ID = UUID("60000000-0000-4000-8000-000000000001")
COLLECTION_ID = UUID("60000000-0000-4000-8000-000000000002")


@pytest.mark.asyncio
async def test_hard_timeout_does_not_wait_for_driver_cancellation() -> None:
    async def slow_cancellation() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)

    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        await hard_timeout(slow_cancellation(), 0.005)
    assert time.perf_counter() - started < 0.04
    await asyncio.sleep(0.06)


class FakeSessions:
    @asynccontextmanager
    async def __call__(self):  # type: ignore[no-untyped-def]
        yield object()


def runtime_state() -> RuntimeState:
    runtime = RuntimeState.__new__(RuntimeState)
    runtime.settings = Settings(
        RISK_KNOWLEDGE_DEPENDENCY_TIMEOUT_SECONDS=1.0,
        RISK_KNOWLEDGE_ARTIFACT_VERIFICATION_TIMEOUT_SECONDS=2.0,
    )
    runtime.database = SimpleNamespace(sessions=FakeSessions(), dispose=AsyncMock())
    runtime.qdrant = SimpleNamespace(
        active_alias_status=AsyncMock(
            return_value=QdrantAliasStatus(True, "sta-knowledge-1.0.0", None)
        ),
        close=AsyncMock(),
    )
    runtime.snapshots = SimpleNamespace(close=AsyncMock())
    runtime.artifacts = SimpleNamespace(
        verify=lambda _record: SimpleNamespace(
            checksum="sha256:" + "a" * 64,
        )
    )
    runtime.model = ModelRuntimeStatus()
    runtime.knowledge = KnowledgeRuntimeStatus()
    return runtime


def active_model() -> ActiveModel:
    return ActiveModel(
        id=MODEL_ID,
        name="route-risk-baseline",
        version="1.0.0",
        stage="ACTIVE",
        feature_schema="1.0.0",
        artifact_uri="model.bin",
        checksum="sha256:" + "a" * 64,
        signature=b"signature",
        signature_algorithm="Ed25519",
        signature_key_id="test-key",
        approved_by="reviewer@example.test",
        approved_at=datetime.now(UTC),
    )


def active_collection(**overrides: Any) -> ActiveCollection:
    values: dict[str, Any] = {
        "id": COLLECTION_ID,
        "version": "1.0.0",
        "collection_name": "sta-knowledge-1.0.0",
        "stage": "ACTIVE",
        "vector_size": 768,
        "manifest_checksum": "sha256:" + "b" * 64,
        "evaluation_checksum": "sha256:" + "c" * 64,
        "approved_by": "reviewer@example.test",
        "approved_at": datetime.now(UTC),
        "document_cutoff": datetime.now(UTC),
    }
    values.update(overrides)
    return ActiveCollection(**values)


@pytest.mark.asyncio
async def test_runtime_model_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = runtime_state()
    monkeypatch.setattr("app.runtime.get_active_model", AsyncMock(return_value=None))
    assert (await runtime.refresh_model()).reason == "NO_APPROVED_ACTIVE_MODEL"

    monkeypatch.setattr("app.runtime.get_active_model", AsyncMock(return_value=active_model()))
    monkeypatch.setattr("app.runtime.RiskPredictor", lambda _path, _reference: object())
    runtime.artifacts.verify = lambda _record: SimpleNamespace(
        checksum="sha256:" + "a" * 64,
        path=tmp_path / "model.bin",
    )
    available = await runtime.refresh_model()
    assert available.status == "AVAILABLE"
    assert available.model is not None and available.model.version == "1.0.0"

    runtime.artifacts.verify = lambda _record: (_ for _ in ()).throw(
        ArtifactUnavailable("ARTIFACT_CHECKSUM_MISMATCH")
    )
    unavailable = await runtime.refresh_model()
    assert unavailable.reason == "ARTIFACT_CHECKSUM_MISMATCH"

    runtime.database.sessions = None
    assert (await runtime.refresh_model()).reason == "DATABASE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_runtime_knowledge_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = runtime_state()
    monkeypatch.setattr(
        "app.runtime.get_active_collection", AsyncMock(return_value=active_collection())
    )
    available = await runtime.refresh_knowledge()
    assert available.status == "AVAILABLE"
    assert available.collection_version == "1.0.0"

    monkeypatch.setattr("app.runtime.get_active_collection", AsyncMock(return_value=None))
    assert (await runtime.refresh_knowledge()).reason == "QDRANT_DATABASE_ALIAS_MISMATCH"

    monkeypatch.setattr(
        "app.runtime.get_active_collection",
        AsyncMock(return_value=active_collection(approved_by=None)),
    )
    assert (await runtime.refresh_knowledge()).reason == "KNOWLEDGE_COLLECTION_NOT_APPROVED"

    runtime.qdrant.active_alias_status = AsyncMock(
        return_value=QdrantAliasStatus(True, None, "Active alias is not configured")
    )
    assert (await runtime.refresh_knowledge()).reason == "NO_ACTIVE_KNOWLEDGE_COLLECTION"

    runtime.qdrant.active_alias_status = AsyncMock(
        return_value=QdrantAliasStatus(False, None, "Qdrant health request failed")
    )
    assert (await runtime.refresh_knowledge()).reason == "Qdrant health request failed"


@pytest.mark.asyncio
async def test_runtime_warmup_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = runtime_state()
    monkeypatch.setattr(runtime, "refresh_model", AsyncMock(return_value=runtime.model))
    monkeypatch.setattr(runtime, "refresh_knowledge", AsyncMock(return_value=runtime.knowledge))
    await runtime.warmup()
    await runtime.close()
    runtime.database.dispose.assert_awaited_once()
    runtime.qdrant.close.assert_awaited_once()
    runtime.snapshots.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_database_reports_configuration_and_migration_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("RISK_KNOWLEDGE_DATABASE_URL", raising=False)
    database = Database(Settings())
    ready, detail = await database.check_ready()
    assert ready is False
    assert detail == "POSTGRES_PASSWORD or RISK_KNOWLEDGE_DATABASE_URL is required"
    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        await anext(database.session())

    result = SimpleNamespace(scalar_one=lambda: False)
    connection = SimpleNamespace(execute=AsyncMock(return_value=result))

    @asynccontextmanager
    async def connect():  # type: ignore[no-untyped-def]
        yield connection

    database.engine = SimpleNamespace(connect=connect, dispose=AsyncMock())
    ready, detail = await database.check_ready()
    assert ready is False
    assert detail == "Knowledge schema migrations are not at a usable baseline"
    result.scalar_one = lambda: True
    assert await database.check_ready() == (True, None)
    await database.dispose()


@pytest.mark.asyncio
async def test_assessment_repositories_materialize_and_commit(snapshot: Any) -> None:
    session = SimpleNamespace(add_all=lambda records: setattr(session, "records", records))
    session.commit = AsyncMock()
    assessments = assess_with_conservative_fallback(
        snapshot, [snapshot.route_candidates[0].route_id]
    )
    await save_fallback_assessments(
        session,
        assessments=assessments,
        input_hash=snapshot.content_hash,
    )
    assert len(session.records) == 1
    assert session.records[0].risk_level == "UNKNOWN"

    await save_fallback_route_evaluations(
        session,
        snapshot_id=snapshot.snapshot_id,
        routes=snapshot.route_candidates,
        unusable_route_ids=[snapshot.route_candidates[0].route_id],
        policy_version="fallback-route-safety-1.0.0",
        input_hash=snapshot.content_hash,
    )
    assert session.records[0].usable is False
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_registry_reads_registers_and_activates() -> None:
    model_row = ModelVersion(
        id=MODEL_ID,
        name="route-risk-baseline",
        version="1.0.0",
        stage="ACTIVE",
        feature_schema="1.0.0",
        metrics_json={},
        artifact_uri="model.bin",
        checksum="sha256:" + "a" * 64,
    )
    collection_row = KnowledgeCollectionVersion(
        id=COLLECTION_ID,
        version="1.0.0",
        collection_name="sta-knowledge-1.0.0",
        stage="APPROVED",
        vector_size=768,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[model_row, collection_row, collection_row, None]),
        add=lambda record: setattr(session, "added", record),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        execute=AsyncMock(side_effect=[SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=1)]),
        rollback=AsyncMock(),
    )
    assert (await get_active_model(session, "route-risk-baseline")).version == "1.0.0"  # type: ignore[union-attr]
    assert (await get_active_collection(session)).collection_name == "sta-knowledge-1.0.0"  # type: ignore[union-attr]
    assert (await get_approved_collection(session, "1.0.0")).version == "1.0.0"  # type: ignore[union-attr]
    draft = await register_draft_collection(
        session,
        version="2.0.0",
        collection_name="sta-knowledge-2.0.0",
        vector_size=768,
    )
    assert draft.stage == "DRAFT"
    await mark_collection_active(session, COLLECTION_ID)
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_registry_rejects_conflicting_draft_and_unapproved_activation() -> None:
    existing = KnowledgeCollectionVersion(
        id=COLLECTION_ID,
        version="1.0.0",
        collection_name="sta-knowledge-1.0.0",
        stage="DRAFT",
        vector_size=768,
    )
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=existing),
        execute=AsyncMock(side_effect=[SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=0)]),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )
    with pytest.raises(ValueError, match="immutable settings"):
        await register_draft_collection(
            session,
            version="1.0.0",
            collection_name="different",
            vector_size=768,
        )
    with pytest.raises(ValueError, match="APPROVED"):
        await mark_collection_active(session, COLLECTION_ID)
    session.rollback.assert_awaited_once()
