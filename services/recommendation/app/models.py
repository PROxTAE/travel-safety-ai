from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

RECOMMENDATION_SCHEMA = "recommendation"


class Base(DeclarativeBase):
    metadata = MetaData()


def utcnow() -> datetime:
    return datetime.now(UTC)


UUID_TYPE = Uuid().with_variant(PGUUID(as_uuid=True), "postgresql")
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class RecommendationModel(Base):
    __tablename__ = "recommendations"
    __table_args__ = {"schema": RECOMMENDATION_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETED")
    action_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class FeedbackModel(Base):
    __tablename__ = "feedback"
    __table_args__ = {"schema": RECOMMENDATION_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    text_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="NEW", index=True
    )
    safety_review_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )


class SubscriptionModel(Base):
    __tablename__ = "subscriptions"
    __table_args__ = {"schema": RECOMMENDATION_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consent_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    min_severity: Mapped[str] = mapped_column(String(32), nullable=False, default="MODERATE")
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeliveryLogModel(Base):
    __tablename__ = "delivery_log"
    __table_args__ = (
        UniqueConstraint("subscription_id", "event_hash", name="uq_delivery_sub_event"),
        {"schema": RECOMMENDATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(UUID_TYPE, nullable=True, index=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_summary: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SafetyReviewQueueModel(Base):
    __tablename__ = "safety_review_queue"
    __table_args__ = {"schema": RECOMMENDATION_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    feedback_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="SEVERE")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmergencyContactModel(Base):
    __tablename__ = "emergency_contacts"
    __table_args__ = (
        UniqueConstraint(
            "country_code",
            "subdivision",
            "service_type",
            name="uq_emergency_contact_scope",
        ),
        {"schema": RECOMMENDATION_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    subdivision: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    service_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    label_i18n: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="VERIFIED", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
