"""initial recommendation schema

Revision ID: 0001_initial_recommendation
Revises: None
Create Date: 2026-09-22 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_recommendation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "recommendation"


def upgrade() -> None:
    # Ensure schema exists
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # 1. recommendations table
    op.create_table(
        "recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="COMPLETED"),
        sa.Column("action_code", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_recommendations_request_id",
        "recommendations",
        ["request_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_recommendations_trip_id", "recommendations", ["trip_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_recommendation_recommendations_action_code",
        "recommendations",
        ["action_code"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_recommendations_risk_level",
        "recommendations",
        ["risk_level"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_recommendations_created_at",
        "recommendations",
        ["created_at"],
        schema=SCHEMA,
    )

    # 2. feedback table
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("text_redacted", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="NEW"),
        sa.Column("safety_review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_recommendation_feedback_user_id", "feedback", ["user_id"], schema=SCHEMA)
    op.create_index(
        "ix_recommendation_feedback_recommendation_id",
        "feedback",
        ["recommendation_id"],
        schema=SCHEMA,
    )
    op.create_index("ix_recommendation_feedback_category", "feedback", ["category"], schema=SCHEMA)
    op.create_index(
        "ix_recommendation_feedback_review_status", "feedback", ["review_status"], schema=SCHEMA
    )

    # 3. subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("destination", sa.String(length=255), nullable=True),
        sa.Column("consent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("min_severity", sa.String(length=32), nullable=False, server_default="MODERATE"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_subscriptions_user_id", "subscriptions", ["user_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_recommendation_subscriptions_trip_id", "subscriptions", ["trip_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_recommendation_subscriptions_consent_id", "subscriptions", ["consent_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_recommendation_subscriptions_status", "subscriptions", ["status"], schema=SCHEMA
    )

    # 4. delivery_log table
    op.create_table(
        "delivery_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("payload_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("subscription_id", "event_hash", name="uq_delivery_sub_event"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_delivery_log_event_hash",
        "delivery_log",
        ["event_hash"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_delivery_log_subscription_id",
        "delivery_log",
        ["subscription_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_delivery_log_status", "delivery_log", ["status"], schema=SCHEMA
    )

    # 5. safety_review_queue table
    op.create_table(
        "safety_review_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feedback_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="SEVERE"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="NEW"),
        sa.Column("assigned_to", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_safety_review_feedback_id",
        "safety_review_queue",
        ["feedback_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_safety_review_status", "safety_review_queue", ["status"], schema=SCHEMA
    )

    # 6. emergency_contacts table
    op.create_table(
        "emergency_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("subdivision", sa.String(length=16), nullable=True),
        sa.Column("service_type", sa.String(length=32), nullable=False),
        sa.Column("label_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("authority", sa.String(length=32), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer", sa.String(length=64), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="VERIFIED"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "country_code", "subdivision", "service_type", name="uq_emergency_contact_scope"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_emergency_contacts_country_code",
        "emergency_contacts",
        ["country_code"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_recommendation_emergency_contacts_service_type",
        "emergency_contacts",
        ["service_type"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("emergency_contacts", schema=SCHEMA)
    op.drop_table("safety_review_queue", schema=SCHEMA)
    op.drop_table("delivery_log", schema=SCHEMA)
    op.drop_table("subscriptions", schema=SCHEMA)
    op.drop_table("feedback", schema=SCHEMA)
    op.drop_table("recommendations", schema=SCHEMA)
