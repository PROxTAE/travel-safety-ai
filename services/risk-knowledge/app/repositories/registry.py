from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeCollectionVersion, ModelVersion


@dataclass(frozen=True)
class ActiveModel:
    id: UUID
    name: str
    version: str
    stage: str
    feature_schema: str
    artifact_uri: str
    checksum: str
    signature: bytes | None
    signature_algorithm: str | None
    signature_key_id: str | None
    approved_by: str | None
    approved_at: datetime | None


@dataclass(frozen=True)
class ActiveCollection:
    id: UUID
    version: str
    collection_name: str
    stage: str
    vector_size: int
    manifest_checksum: str | None
    evaluation_checksum: str | None
    approved_by: str | None
    approved_at: datetime | None
    document_cutoff: datetime | None


def _active_model(row: ModelVersion) -> ActiveModel:
    return ActiveModel(
        id=row.id,
        name=row.name,
        version=row.version,
        stage=row.stage,
        feature_schema=row.feature_schema,
        artifact_uri=row.artifact_uri,
        checksum=row.checksum,
        signature=row.signature,
        signature_algorithm=row.signature_algorithm,
        signature_key_id=row.signature_key_id,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
    )


def _active_collection(row: KnowledgeCollectionVersion) -> ActiveCollection:
    return ActiveCollection(
        id=row.id,
        version=row.version,
        collection_name=row.collection_name,
        stage=row.stage,
        vector_size=row.vector_size,
        manifest_checksum=row.manifest_checksum,
        evaluation_checksum=row.evaluation_checksum,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        document_cutoff=row.document_cutoff,
    )


async def get_active_model(session: AsyncSession, name: str) -> ActiveModel | None:
    row = await session.scalar(
        select(ModelVersion).where(ModelVersion.name == name, ModelVersion.stage == "ACTIVE")
    )
    return _active_model(row) if row else None


async def get_active_collection(session: AsyncSession) -> ActiveCollection | None:
    row = await session.scalar(
        select(KnowledgeCollectionVersion).where(KnowledgeCollectionVersion.stage == "ACTIVE")
    )
    return _active_collection(row) if row else None


async def register_draft_collection(
    session: AsyncSession,
    *,
    version: str,
    collection_name: str,
    vector_size: int,
) -> KnowledgeCollectionVersion:
    existing = await session.scalar(
        select(KnowledgeCollectionVersion).where(KnowledgeCollectionVersion.version == version)
    )
    if existing:
        if existing.collection_name != collection_name or existing.vector_size != vector_size:
            raise ValueError("Existing collection version has different immutable settings")
        return existing
    record = KnowledgeCollectionVersion(
        version=version,
        collection_name=collection_name,
        stage="DRAFT",
        vector_size=vector_size,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_approved_collection(session: AsyncSession, version: str) -> ActiveCollection | None:
    row = await session.scalar(
        select(KnowledgeCollectionVersion).where(
            KnowledgeCollectionVersion.version == version,
            KnowledgeCollectionVersion.stage == "APPROVED",
        )
    )
    return _active_collection(row) if row else None


async def mark_collection_active(session: AsyncSession, collection_id: UUID) -> None:
    await session.execute(
        update(KnowledgeCollectionVersion)
        .where(KnowledgeCollectionVersion.stage == "ACTIVE")
        .values(stage="RETIRED")
    )
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(KnowledgeCollectionVersion)
            .where(
                KnowledgeCollectionVersion.id == collection_id,
                KnowledgeCollectionVersion.stage == "APPROVED",
            )
            .values(stage="ACTIVE")
        ),
    )
    if result.rowcount != 1:
        await session.rollback()
        raise ValueError("Collection must be APPROVED before activation")
    await session.commit()
