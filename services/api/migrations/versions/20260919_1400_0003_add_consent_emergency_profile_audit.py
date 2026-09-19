"""Add consents, emergency profiles, the audit log and data subject requests.

Revision ID: 0003
Revises: 0002
Create date: 2026-09-19

Why:
    Phase 3 of the module plan. Four tables, reviewed statement by statement rather than taken as
    autogenerate produced them.

    `consents` is append-only and carries `policy_version`, because the record has to answer what
    someone agreed to and when, not merely whether a flag is set. `expires_at` is what keeps a
    location grant from outliving its errand.

    `emergency_profiles` stores ciphertext and the metadata needed to open it, and nothing else.
    There is no blood-type column and no allergy column: the searchable copy is the copy that leaks.

    `audit_log` records that an action happened, never its content, per the plan's requirement that
    the audit trail carry no sensitive data.

    `data_subject_requests` tracks export and deletion separately from the work itself, because
    deleting everything about someone needs other services that do not exist yet.
    `incomplete_scopes` exists so COMPLETED is never read as "erased everywhere".

Data impact:
    Four empty tables and five indexes. No rewrite and no lock of consequence: `user_profiles` is
    only referenced, not altered.

    Two partial indexes carry the load of the queries that run most: the standing consents for one
    user, and the queue of unfinished data-subject requests.

Downgrade:
    Drops all four. Safe while they are empty, which they are until the first consent is recorded.
    Once they hold anything this becomes a forward-fix — and note that dropping `audit_log`
    destroys the record of what was done to accounts, which is the one table whose loss cannot be
    reconstructed from anywhere else.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=True,
            comment="Nulled when the account is purged; the action still happened.",
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
            comment="Counts, versions and enum values only; never a field the person typed.",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.user_profiles.id"],
            name=op.f("fk_audit_log_user_id_user_profiles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        schema="identity",
    )
    op.create_index(
        "ix_audit_log_user_occurred",
        "audit_log",
        ["user_id", "occurred_at"],
        unique=False,
        schema="identity",
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column(
            "policy_version",
            sa.String(length=32),
            nullable=False,
            comment="Version of the consent text the person saw.",
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.user_profiles.id"],
            name=op.f("fk_consents_user_id_user_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
        schema="identity",
    )
    op.create_index(
        "ix_consents_user_active",
        "consents",
        ["user_id", "type"],
        unique=False,
        schema="identity",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_consents_user_granted_at",
        "consents",
        ["user_id", "granted_at"],
        unique=False,
        schema="identity",
    )
    op.create_table(
        "data_subject_requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "incomplete_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Schemas this run could not reach; COMPLETED never means erased everywhere.",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.user_profiles.id"],
            name=op.f("fk_data_subject_requests_user_id_user_profiles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_subject_requests")),
        schema="identity",
    )
    op.create_index(
        "ix_data_subject_requests_pending",
        "data_subject_requests",
        ["status", "requested_at"],
        unique=False,
        schema="identity",
        postgresql_where=sa.text("status IN ('PENDING', 'IN_PROGRESS')"),
    )
    op.create_table(
        "emergency_profiles",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column(
            "wrapped_key",
            sa.LargeBinary(),
            nullable=False,
            comment="Per-record data key, sealed under the key named by key_version.",
        ),
        sa.Column("wrapped_key_nonce", sa.LargeBinary(), nullable=False),
        sa.Column(
            "key_version",
            sa.String(length=32),
            nullable=False,
            comment="Which key-encryption key opens this row.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.user_profiles.id"],
            name=op.f("fk_emergency_profiles_user_id_user_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_emergency_profiles")),
        sa.UniqueConstraint("user_id", name=op.f("uq_emergency_profiles_user_id")),
        schema="identity",
    )


def downgrade() -> None:
    op.drop_table("emergency_profiles", schema="identity")
    op.drop_index(
        "ix_data_subject_requests_pending",
        table_name="data_subject_requests",
        schema="identity",
        postgresql_where=sa.text("status IN ('PENDING', 'IN_PROGRESS')"),
    )
    op.drop_table("data_subject_requests", schema="identity")
    op.drop_index("ix_consents_user_granted_at", table_name="consents", schema="identity")
    op.drop_index(
        "ix_consents_user_active",
        table_name="consents",
        schema="identity",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_table("consents", schema="identity")
    op.drop_index("ix_audit_log_user_occurred", table_name="audit_log", schema="identity")
    op.drop_table("audit_log", schema="identity")
