"""Create the module 06 knowledge schema foundation.

Revision ID: 20260919_0001
Revises:
Create Date: 2026-09-19 00:00:00+07:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260919_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "knowledge"


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("feature_schema", sa.String(length=50), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_uri", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=71), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=True),
        sa.Column("signature_algorithm", sa.String(length=30), nullable=True),
        sa.Column("signature_key_id", sa.String(length=200), nullable=True),
        sa.Column("approved_by", sa.String(length=200), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('CANDIDATE', 'APPROVED', 'ACTIVE', 'RETIRED')",
            name="ck_model_versions_stage",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_model_versions_name_version"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_model_versions_one_active_per_name",
        "model_versions",
        ["name"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("stage = 'ACTIVE'"),
    )

    op.create_table(
        "risk_assessments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("probability_high", sa.Float(), nullable=True),
        sa.Column("uncertainty", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("safety_overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.String(length=71), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'UNKNOWN')", name="ck_risk_level"
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["knowledge.model_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_risk_assessments_snapshot_route",
        "risk_assessments",
        ["snapshot_id", "route_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("document_id", sa.String(length=300), nullable=False),
        sa.Column("authority", sa.String(length=50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("regions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hazards", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum", sa.String(length=71), nullable=False),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')",
            name="ck_documents_review_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_documents_document_id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_documents_scope",
        "documents",
        ["language", "effective_at", "expires_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text_hash", sa.String(length=71), nullable=False),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_version", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge.documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "qdrant_point_id", "collection_version", name="uq_chunks_qdrant_collection"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], schema=SCHEMA)

    op.create_table(
        "collection_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("collection_name", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("vector_size", sa.Integer(), nullable=False),
        sa.Column("manifest_checksum", sa.String(length=71), nullable=True),
        sa.Column("evaluation_checksum", sa.String(length=71), nullable=True),
        sa.Column("approved_by", sa.String(length=200), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_cutoff", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('DRAFT', 'APPROVED', 'ACTIVE', 'RETIRED')",
            name="ck_collection_versions_stage",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_name", name="uq_collection_versions_name"),
        sa.UniqueConstraint("version", name="uq_collection_versions_version"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_collection_versions_one_active",
        "collection_versions",
        ["stage"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("stage = 'ACTIVE'"),
    )

    op.create_table(
        "route_evaluations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("exposure_score", sa.Float(), nullable=True),
        sa.Column("usable", sa.Boolean(), nullable=False),
        sa.Column("hard_constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tradeoffs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.String(length=71), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_route_evaluations_snapshot_route",
        "route_evaluations",
        ["snapshot_id", "route_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_route_evaluations_snapshot_route", table_name="route_evaluations", schema=SCHEMA
    )
    op.drop_table("route_evaluations", schema=SCHEMA)
    op.drop_index(
        "uq_collection_versions_one_active", table_name="collection_versions", schema=SCHEMA
    )
    op.drop_table("collection_versions", schema=SCHEMA)
    op.drop_index("ix_chunks_document_id", table_name="chunks", schema=SCHEMA)
    op.drop_table("chunks", schema=SCHEMA)
    op.drop_index("ix_documents_scope", table_name="documents", schema=SCHEMA)
    op.drop_table("documents", schema=SCHEMA)
    op.drop_index(
        "ix_risk_assessments_snapshot_route", table_name="risk_assessments", schema=SCHEMA
    )
    op.drop_table("risk_assessments", schema=SCHEMA)
    op.drop_index(
        "uq_model_versions_one_active_per_name", table_name="model_versions", schema=SCHEMA
    )
    op.drop_table("model_versions", schema=SCHEMA)
