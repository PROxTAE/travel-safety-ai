"""Storage models scoped to the integration schema."""

from datetime import datetime
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint(
            "request_id", "input_content_hash", "schema_version", name="uq_snapshot_input"
        ),
        Index("ix_snapshot_corridor", "route_corridor", postgresql_using="gist"),
        {"schema": "integration"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    input_content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_schema_version: Mapped[str | None] = mapped_column(String(32))
    evidence_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Null for snapshots stored before migration 0006; those cannot be rebuilt.
    request_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    route_corridor = mapped_column(
        Geometry("GEOMETRY", srid=4326, spatial_index=False), nullable=True
    )
    supersedes_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("integration.snapshots.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Quarantine(Base):
    __tablename__ = "quarantine"
    __table_args__ = (
        Index("ix_quarantine_status_created", "status", "created_at"),
        {"schema": "integration"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    raw_content: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FieldLineage(Base):
    __tablename__ = "field_lineage"
    __table_args__ = (Index("ix_lineage_source", "source_id"), {"schema": "integration"})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("integration.snapshots.id"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(String(256), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    transform_id: Mapped[str | None] = mapped_column(String(128))
    transform_version: Mapped[str | None] = mapped_column(String(32))


class CanonicalRecord(Base):
    __tablename__ = "canonical_records"
    __table_args__ = (
        UniqueConstraint("record_type", "source_id", "content_hash", name="uq_canonical_version"),
        Index("ix_canonical_geometry", "geometry", postgresql_using="gist"),
        Index("ix_canonical_valid_at", "valid_at"),
        {"schema": "integration"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    transform_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    lineage_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    geometry = mapped_column(Geometry("GEOMETRY", srid=4326, spatial_index=False))
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DedupCluster(Base):
    __tablename__ = "dedup_clusters"
    __table_args__ = (
        UniqueConstraint("record_type", "cluster_key", "match_version", name="uq_dedup_cluster"),
        Index("ix_dedup_cluster_created", "created_at"),
        {"schema": "integration"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cluster_key: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    match_version: Mapped[str] = mapped_column(String(32), nullable=False)
    members_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    matches_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    conflicts_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
