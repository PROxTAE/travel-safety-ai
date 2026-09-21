"""Feedback and alert subscription models.

Mirrors `feedback-event.schema.json`, `alert-subscription.schema.json` and `public-api.yaml`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.envelope import ResponseMeta

FeedbackCategory = Literal[
    "HELPFUL", "INCORRECT", "STALE", "UNSAFE", "ROUTE_ISSUE", "SOURCE_ISSUE", "OTHER"
]
DeliveryChannel = Literal["IN_APP", "EMAIL", "SMS", "PUSH"]
SubscriptionStatus = Literal["ACTIVE", "PAUSED", "CANCELLED", "EXPIRED"]
Severity = Literal["INFO", "MINOR", "MODERATE", "SEVERE", "EXTREME", "UNKNOWN"]


class FeedbackRequest(BaseModel):
    """Explicit feedback submitted on a recommendation."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: UUID
    category: FeedbackCategory
    text: Annotated[str | None, Field(max_length=2000)] = None


class FeedbackEventModel(BaseModel):
    """An explicit feedback event recorded in the system."""

    model_config = ConfigDict(frozen=True)

    feedback_id: UUID
    recommendation_id: UUID
    category: FeedbackCategory
    text_redacted: Annotated[str | None, Field(max_length=2000)] = None
    review_status: Literal["NEW", "TRIAGED", "IN_REVIEW", "RESOLVED", "DISMISSED"]
    safety_review_id: UUID | None = None
    created_at: datetime


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: FeedbackEventModel
    meta: ResponseMeta


class CreateAlertSubscriptionRequest(BaseModel):
    """Opting into live safety alerts for a saved trip."""

    model_config = ConfigDict(extra="forbid")

    trip_id: UUID
    channel: DeliveryChannel
    consent_id: UUID
    min_severity: Severity = "MODERATE"


class AlertSubscriptionModel(BaseModel):
    """One standing subscription to hazard notifications."""

    model_config = ConfigDict(frozen=True)

    subscription_id: UUID
    trip_id: UUID
    channel: DeliveryChannel
    consent_id: UUID
    status: SubscriptionStatus
    min_severity: Severity | None = None
    cooldown_until: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    cancelled_at: datetime | None = None


class AlertSubscriptionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: AlertSubscriptionModel
    meta: ResponseMeta
