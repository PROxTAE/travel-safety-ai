"""Persist immutable dedup decisions and all competing evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_dedup_clusters"
down_revision = "0003_canonical_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dedup_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("record_type", sa.String(32), nullable=False),
        sa.Column("cluster_key", sa.String(80), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("match_version", sa.String(32), nullable=False),
        sa.Column("members_json", postgresql.JSONB, nullable=False),
        sa.Column("matches_json", postgresql.JSONB, nullable=False),
        sa.Column("conflicts_json", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("record_type", "cluster_key", "match_version", name="uq_dedup_cluster"),
        schema="integration",
    )
    op.create_index(
        "ix_dedup_cluster_created", "dedup_clusters", ["created_at"], schema="integration"
    )


def downgrade() -> None:
    op.drop_table("dedup_clusters", schema="integration")
