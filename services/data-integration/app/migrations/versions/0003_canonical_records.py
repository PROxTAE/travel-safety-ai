"""Versioned canonical source records with spatial and temporal indexes."""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = "0003_canonical_records"
down_revision = "0002_snapshot_immutability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("record_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("transform_version", sa.String(32), nullable=False),
        sa.Column("payload_json", postgresql.JSONB, nullable=False),
        sa.Column("lineage_json", postgresql.JSONB, nullable=False),
        sa.Column("geometry", Geometry("GEOMETRY", srid=4326, spatial_index=False)),
        sa.Column("valid_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "record_type", "source_id", "content_hash", name="uq_canonical_version"
        ),
        schema="integration",
    )
    op.create_index(
        "ix_canonical_geometry",
        "canonical_records",
        ["geometry"],
        postgresql_using="gist",
        schema="integration",
    )
    op.create_index(
        "ix_canonical_valid_at", "canonical_records", ["valid_at"], schema="integration"
    )


def downgrade() -> None:
    op.drop_table("canonical_records", schema="integration")
