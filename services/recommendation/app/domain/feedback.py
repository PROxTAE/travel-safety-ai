from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.observability import redact_pii_string

FeedbackCategory = Literal[
    "HELPFUL", "INCORRECT", "STALE", "UNSAFE", "ROUTE_ISSUE", "SOURCE_ISSUE", "OTHER"
]
ReviewStatus = Literal["NEW", "TRIAGED", "IN_REVIEW", "RESOLVED", "DISMISSED"]


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    recommendation_id: str
    category: FeedbackCategory
    text: str | None = Field(default=None, max_length=2000)


class FeedbackEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    feedback_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    recommendation_id: str
    category: FeedbackCategory
    text_redacted: str | None = None
    review_status: ReviewStatus = "NEW"
    safety_review_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SafetyReviewItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    feedback_id: str
    severity: Literal["INFO", "MINOR", "MODERATE", "SEVERE", "EXTREME"] = "SEVERE"
    status: ReviewStatus = "NEW"
    assigned_to: str | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None


VALID_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    "NEW": {"TRIAGED", "IN_REVIEW", "RESOLVED", "DISMISSED"},
    "TRIAGED": {"IN_REVIEW", "RESOLVED", "DISMISSED"},
    "IN_REVIEW": {"RESOLVED", "DISMISSED"},
    "RESOLVED": {"IN_REVIEW"},  # can reopen
    "DISMISSED": {"IN_REVIEW"},  # can reopen
}


def sanitize_feedback_text(raw_text: str | None) -> str | None:
    if not raw_text:
        return None
    # Truncate to 2000 chars
    truncated = raw_text[:2000]
    # Redact PII (phones, emails, exact coordinates)
    return redact_pii_string(truncated)


def is_safety_critical_feedback(category: FeedbackCategory) -> bool:
    return category in ("UNSAFE", "INCORRECT", "ROUTE_ISSUE")
