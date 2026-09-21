"""Create integration storage and spatial indexes."""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = "0001_integration_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE SCHEMA IF NOT EXISTS integration")
    op.create_table(
        "snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_content_hash", sa.String(80), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("feature_schema_version", sa.String(32)),
        sa.Column("evidence_json", postgresql.JSONB, nullable=False),
        sa.Column("route_corridor", Geometry("GEOMETRY", srid=4326, spatial_index=False)),
        sa.Column(
            "supersedes_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("integration.snapshots.id"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "request_id", "input_content_hash", "schema_version", name="uq_snapshot_input"
        ),
        schema="integration",
    )
    op.create_index(
        "ix_integration_snapshots_request_id", "snapshots", ["request_id"], schema="integration"
    )
    op.create_index(
        "ix_snapshot_corridor",
        "snapshots",
        ["route_corridor"],
        unique=False,
        postgresql_using="gist",
        schema="integration",
    )
    op.create_table(
        "quarantine",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_hash", sa.String(80), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=False),
        sa.Column("field_path", sa.String(256)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("raw_content", postgresql.JSONB),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="integration",
    )
    op.create_index(
        "ix_quarantine_status_created", "quarantine", ["status", "created_at"], schema="integration"
    )
    op.create_table(
        "field_lineage",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("integration.snapshots.id"),
            nullable=False,
        ),
        sa.Column("field_path", sa.String(256), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("transform_id", sa.String(128)),
        sa.Column("transform_version", sa.String(32)),
        schema="integration",
    )
    op.create_index("ix_lineage_source", "field_lineage", ["source_id"], schema="integration")


def downgrade() -> None:
    op.drop_table("field_lineage", schema="integration")
    op.drop_table("quarantine", schema="integration")
    op.drop_table("snapshots", schema="integration")
