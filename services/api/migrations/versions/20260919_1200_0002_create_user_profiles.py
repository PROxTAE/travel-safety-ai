"""Create identity.user_profiles.

Revision ID: 0002
Revises: 0001
Create date: 2026-09-19

Why:
    Phase 2 has to map an OIDC `sub` onto an internal user id. Every owner-scoped query in every
    later phase filters on that id, so it has to exist before any resource does.

    The Keycloak subject gets its own column and the primary key is an internal UUID, per
    §"User identity" of the module plan. E-mail is deliberately absent: it changes, it is reused,
    and it is personal data, so it is neither a key nor stored at all.

    `disabled_at` exists because a JWT cannot be withdrawn once issued. Without a local flag,
    disabling an account would leave it working until its token expired.

Data impact:
    Creates one empty table plus two indexes. No rewrite, no lock of consequence.

Downgrade:
    Drops the table. Safe while it is empty, which it is until the first sign-in; once real users
    exist this becomes a forward-fix, because dropping it discards the id every other table
    references.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.String(length=255),
            nullable=False,
            comment="OIDC subject; opaque and stable for the life of the provider account.",
        ),
        sa.Column(
            "locale", sa.String(length=35), server_default=sa.text("'en-US'"), nullable=False
        ),
        sa.Column(
            "timezone", sa.String(length=64), server_default=sa.text("'UTC'"), nullable=False
        ),
        sa.Column("home_country_code", sa.String(length=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "disabled_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set to refuse a caller who still holds a valid, unexpired token.",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft delete; the purge of owned data runs asynchronously under retention.",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profiles")),
        # One profile per identity-provider subject. This is what makes get-or-create safe when a
        # freshly signed-in browser fires several requests at once.
        sa.UniqueConstraint("subject_id", name=op.f("uq_user_profiles_subject_id")),
        schema=SCHEMA,
    )

    # Partial: the disable check runs on every authenticated request, and only the few disabled
    # rows are worth an index entry.
    op.create_index(
        "ix_user_profiles_disabled",
        "user_profiles",
        ["disabled_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("disabled_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_user_profiles_disabled", table_name="user_profiles", schema=SCHEMA)
    op.drop_table("user_profiles", schema=SCHEMA)
