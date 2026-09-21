"""create provider schema: providers, fetch_log, health

Revision ID: 0001_provider_schema
Revises:
Create Date: 2026-09-19

Creates the `provider` schema owned by module 04, per
00_API_AND_DATA_CONTRACTS.md § 8.

The schema is created here rather than relying on
infra/postgres/init/00-schemas.sql, which creates `external_data` instead. That
file is infra-owned and disagrees with the contract; see the module handoff for
the proposed fix. Creating our own schema keeps this service correct and
self-sufficient on a fresh database either way.

No raw provider body column exists anywhere in this migration - that is the
retention default, not an omission.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_provider_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "provider"


def upgrade() -> None:
    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))

    op.create_table(
        "providers",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "coverage_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("license_url", sa.Text(), nullable=True),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    op.create_table(
        "fetch_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("query_hash", sa.String(length=80), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=80), nullable=True),
        sa.Column(
            "quality_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["provider_id"], [f"{SCHEMA}.providers.id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_fetch_log_provider_fetched_at",
        "fetch_log",
        ["provider_id", "fetched_at"],
        schema=SCHEMA,
    )
    op.create_index("ix_fetch_log_fetched_at", "fetch_log", ["fetched_at"], schema=SCHEMA)

    op.create_table(
        "health",
        sa.Column("provider_id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("quota_remaining", sa.Integer(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], [f"{SCHEMA}.providers.id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("health", schema=SCHEMA)
    op.drop_index("ix_fetch_log_fetched_at", table_name="fetch_log", schema=SCHEMA)
    op.drop_index("ix_fetch_log_provider_fetched_at", table_name="fetch_log", schema=SCHEMA)
    op.drop_table("fetch_log", schema=SCHEMA)
    op.drop_table("providers", schema=SCHEMA)
    # The schema itself is left in place: dropping it would also remove the
    # alembic_version table that records this downgrade.
