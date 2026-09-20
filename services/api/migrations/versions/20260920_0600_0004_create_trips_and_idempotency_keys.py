"""Create trips and idempotency keys.

Revision ID: 0004
Revises: 0003
Create date: 2026-09-20

Why:
    Phase 4 of the module plan, and the first tables in the `travel` schema.

    `trips` stores origin and destination as JSONB rather than as columns. They are a contract
    entity (`LocationRef`) that module 04 produces and this service stores whole: splitting it into
    eight columns would mean a migration here every time that entity gains a field, and would drop
    the provider that resolved the place — which is the provenance a later assessment needs.

    `revision` is the optimistic concurrency token, served to clients as the ETag. An integer and
    not a timestamp: two writes inside the same millisecond are indistinguishable by clock, and
    simultaneous writes are exactly the case this column exists to resolve.

    `idempotency_keys` makes a retried POST safe. It stores digests, never the key or the body:
    the key is a bearer value and the body carries the coordinates of somebody's journey.

Data impact:
    Two empty tables, four indexes and three check constraints. Nothing is rewritten and nothing in
    `identity` is altered — `user_profiles` is referenced, not changed, so no lock of consequence
    is taken on a table that every authenticated request reads.

    The two partial indexes are the ones that carry load. `ix_trips_owner_departure` serves the
    list endpoint and excludes soft-deleted rows from the index rather than from the result set
    after a scan; `ix_trips_deleted_at` indexes only the rows the retention purge looks at.

Downgrade:
    Drops both tables, which destroys every saved trip. Safe while they are empty, which they are
    until the first trip is created. After that this is a forward-fix: a trip is a person's own
    record of a journey they are taking, and other services hold assessments that reference these
    ids, so restoring the table alone would not restore the relationships.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Owner. Every query in the repository filters on it.",
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
            comment=(
                "Optimistic concurrency token, served as the ETag. Incremented by every mutation."
            ),
        ),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column(
            "origin",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="LocationRef as the contract defines it, stored whole with its provider.",
        ),
        sa.Column("destination", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("departure_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("return_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            comment=(
                "IANA zone the traveller planned in. Kept beside the UTC instants because "
                "'09:30 local' survives a daylight-saving change and an offset does not."
            ),
        ),
        sa.Column("travel_modes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "selected_route_id",
            sa.UUID(),
            nullable=True,
            comment=(
                "Set only by apply-route, after the server has checked the route is not closed."
            ),
        ),
        sa.Column("previous_selected_route_id", sa.UUID(), nullable=True),
        sa.Column(
            "latest_request_id",
            sa.UUID(),
            nullable=True,
            comment=(
                "Most recent assessment started for this trip. Cleared when the journey changes."
            ),
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'DRAFT'"), nullable=False
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
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=("Soft delete; the purge of child data runs asynchronously under retention."),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_trips_revision_positive")),
        sa.CheckConstraint(
            "return_time IS NULL OR return_time > departure_time",
            name=op.f("ck_trips_return_after_departure"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(travel_modes) BETWEEN 1 AND 7",
            name=op.f("ck_trips_modes_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.user_profiles.id"],
            name=op.f("fk_trips_user_id_user_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trips")),
        schema="travel",
    )
    op.create_index(
        "ix_trips_owner_departure",
        "trips",
        ["user_id", sa.text("departure_time DESC"), sa.text("id DESC")],
        unique=False,
        schema="travel",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_trips_deleted_at",
        "trips",
        ["deleted_at"],
        unique=False,
        schema="travel",
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "key_digest",
            sa.String(length=64),
            nullable=False,
            comment="SHA-256 of the client's key. The key itself is never stored.",
        ),
        sa.Column(
            "request_digest",
            sa.String(length=64),
            nullable=False,
            comment=(
                "SHA-256 of the canonical request body, so the same key with a different payload "
                "is detected as a conflict rather than answered with the wrong resource."
            ),
        ),
        sa.Column(
            "operation",
            sa.String(length=64),
            nullable=False,
            comment="Which endpoint claimed the key.",
        ),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="After this the key may be reused; the retention job removes the row.",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.user_profiles.id"],
            name=op.f("fk_idempotency_keys_user_id_user_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("user_id", "key_digest", name="uq_idempotency_user_key"),
        schema="travel",
    )
    op.create_index(
        "ix_idempotency_keys_expires_at",
        "idempotency_keys",
        ["expires_at"],
        unique=False,
        schema="travel",
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_expires_at", table_name="idempotency_keys", schema="travel")
    op.drop_table("idempotency_keys", schema="travel")
    op.drop_index(
        "ix_trips_deleted_at",
        table_name="trips",
        schema="travel",
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.drop_index(
        "ix_trips_owner_departure",
        table_name="trips",
        schema="travel",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("trips", schema="travel")
