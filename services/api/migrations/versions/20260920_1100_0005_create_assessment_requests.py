"""Create assessment requests.

Revision ID: 0005
Revises: 0004
Create date: 2026-09-20

Why:
    Phase 5 of the module plan. `travel.requests` is the record of an assessment run, and it exists
    so that a run is never lost: the row is committed before the agent is called, so a crash, a
    timeout or an agent that is down still leaves something the client can poll and an operator can
    find. Calling first and writing afterwards loses the request in exactly the case where the
    traveller most needs to know what happened.

    It is also the authority on status. The agent reports progress; what this service will tell a
    traveller is what is written here, after the state machine in `app/domain/run.py` has decided
    the report was a legal move. The `status_known` check constraint is the database's half of that
    agreement — a status outside the contract cannot be stored even if a future code path tries.

    What the table deliberately does not hold: the question the traveller typed, any prompt, any
    chain-of-thought, any provider payload. `input_digest` is a hash, enough to recognise a retry
    and to tell two runs apart, and nothing more.

Data impact:
    One empty table and three indexes. `trips` and `user_profiles` are referenced, not altered, so
    no lock of consequence is taken on tables that live traffic reads.

    `ix_requests_active` is partial: it indexes only QUEUED, RUNNING and NEEDS_INPUT rows, which is
    the handful in flight at any moment rather than every run the system has ever done.

Downgrade:
    Drops the table, which destroys the history of what was assessed and when. Safe while empty.
    After that it is a forward-fix: module 03 holds agent runs and module 08 holds recommendations
    that reference these ids, so restoring this table alone would not restore the relationships.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KNOWN_STATUSES = (
    "status IN ('QUEUED','RUNNING','NEEDS_INPUT','COMPLETED','PARTIAL','FAILED','CANCELLED')"
)
ACTIVE_STATUSES = "status IN ('QUEUED','RUNNING','NEEDS_INPUT')"


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="The request_id the client polls and streams by.",
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Owner. Every query in the repository filters on it.",
        ),
        sa.Column(
            "trip_id",
            sa.UUID(),
            nullable=True,
            comment="Null for a conversation-only run, which phase 6 adds.",
        ),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'QUEUED'"),
            nullable=False,
            comment="Advanced only through app.domain.run, which refuses backwards moves.",
        ),
        sa.Column(
            "stage",
            sa.String(length=32),
            nullable=True,
            comment="Display hint from the agent; dropped if unrecognised.",
        ),
        sa.Column(
            "percent",
            sa.Integer(),
            nullable=True,
            comment="Null whenever the remaining work cannot be estimated honestly.",
        ),
        sa.Column(
            "message_key",
            sa.String(length=128),
            nullable=True,
            comment="Translation key. Never a rendered sentence, which would be one locale's only.",
        ),
        sa.Column(
            "missing_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "agent_run_id",
            sa.String(length=128),
            nullable=True,
            comment="Module 03's id for the same run. Null until the agent has accepted it.",
        ),
        sa.Column(
            "recommendation_id",
            sa.UUID(),
            nullable=True,
            comment="Set only after the recommendation has been validated against the contract.",
        ),
        sa.Column(
            "error_code",
            sa.String(length=64),
            nullable=True,
            comment="A contract error code, never a downstream message.",
        ),
        sa.Column(
            "error_message",
            sa.String(length=512),
            nullable=True,
            comment="Safe, already-sanitised text. No stack, no host, no provider body.",
        ),
        sa.Column(
            "degraded_services",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="What was unavailable while this ran, so a thin answer is explainable.",
        ),
        sa.Column(
            "input_digest",
            sa.String(length=64),
            nullable=False,
            comment=(
                "SHA-256 of the normalised agent input. Lets a retry be recognised and lets an "
                "operator tell two runs apart without storing what was asked."
            ),
        ),
        sa.Column("contract_version", sa.String(length=16), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(KNOWN_STATUSES, name="ck_requests_status_known"),
        sa.CheckConstraint(
            "percent IS NULL OR (percent BETWEEN 0 AND 100)",
            name="ck_requests_percent_bounded",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_requests_completed_after_created",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.user_profiles.id"],
            name="fk_requests_user_id_user_profiles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trip_id"],
            ["travel.trips.id"],
            name="fk_requests_trip_id_trips",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_requests"),
        schema="travel",
    )
    op.create_index(
        "ix_requests_owner_created",
        "requests",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
        schema="travel",
    )
    op.create_index(
        "ix_requests_active",
        "requests",
        ["status", "created_at"],
        unique=False,
        schema="travel",
        postgresql_where=sa.text(ACTIVE_STATUSES),
    )
    op.create_index("ix_requests_trip", "requests", ["trip_id"], unique=False, schema="travel")


def downgrade() -> None:
    op.drop_index("ix_requests_trip", table_name="requests", schema="travel")
    op.drop_index("ix_requests_active", table_name="requests", schema="travel")
    op.drop_index("ix_requests_owner_created", table_name="requests", schema="travel")
    op.drop_table("requests", schema="travel")
