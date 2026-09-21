from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

KNOWLEDGE_SCHEMA = "knowledge"
metadata = MetaData(schema=KNOWLEDGE_SCHEMA)


class Base(DeclarativeBase):
    metadata = metadata


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_model_versions_name_version"),
        CheckConstraint(
            "stage IN ('CANDIDATE', 'APPROVED', 'ACTIVE', 'RETIRED')",
            name="ck_model_versions_stage",
        ),
        Index(
            "uq_model_versions_one_active_per_name",
            "name",
            unique=True,
            postgresql_where=text("stage = 'ACTIVE'"),
        ),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    feature_schema: Mapped[str] = mapped_column(String(50), nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(71), nullable=False)
    signature: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    signature_algorithm: Mapped[str | None] = mapped_column(String(30), nullable=True)
    signature_key_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class RiskAssessmentRecord(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        CheckConstraint("risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'UNKNOWN')", name="ck_risk_level"),
        Index("ix_risk_assessments_snapshot_route", "snapshot_id", "route_id"),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    route_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    model_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{KNOWLEDGE_SCHEMA}.model_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    safety_overrides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class KnowledgeDocument(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_documents_document_id"),
        CheckConstraint(
            "review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')",
            name="ck_documents_review_status",
        ),
        Index("ix_documents_scope", "language", "effective_at", "expires_at"),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(String(300), nullable=False)
    authority: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    hazards: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum: Mapped[str] = mapped_column(String(71), nullable=False)
    license: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class KnowledgeChunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "qdrant_point_id", "collection_version", name="uq_chunks_qdrant_collection"
        ),
        Index("ix_chunks_document_id", "document_id"),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{KNOWLEDGE_SCHEMA}.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    qdrant_point_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    collection_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class KnowledgeCollectionVersion(Base):
    __tablename__ = "collection_versions"
    __table_args__ = (
        UniqueConstraint("version", name="uq_collection_versions_version"),
        UniqueConstraint("collection_name", name="uq_collection_versions_name"),
        CheckConstraint(
            "stage IN ('DRAFT', 'APPROVED', 'ACTIVE', 'RETIRED')",
            name="ck_collection_versions_stage",
        ),
        Index(
            "uq_collection_versions_one_active",
            "stage",
            unique=True,
            postgresql_where=text("stage = 'ACTIVE'"),
        ),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    vector_size: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_checksum: Mapped[str | None] = mapped_column(String(71), nullable=True)
    evaluation_checksum: Mapped[str | None] = mapped_column(String(71), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class RouteEvaluation(Base):
    __tablename__ = "route_evaluations"
    __table_args__ = (
        Index("ix_route_evaluations_snapshot_route", "snapshot_id", "route_id"),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    route_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    exposure_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    usable: Mapped[bool] = mapped_column(nullable=False)
    hard_constraints: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    tradeoffs_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
