from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feedback import (
    VALID_TRANSITIONS,
    FeedbackCreate,
    FeedbackEvent,
    ReviewStatus,
    SafetyReviewItem,
    is_safety_critical_feedback,
    sanitize_feedback_text,
)
from app.models import FeedbackModel, SafetyReviewQueueModel
from app.observability import FEEDBACK_SUBMISSIONS_TOTAL, SAFETY_REVIEW_QUEUE_SIZE


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_feedback(self, data: FeedbackCreate) -> FeedbackEvent:
        feedback_id = uuid.uuid4()
        user_uuid = uuid.UUID(data.user_id)
        rec_uuid = uuid.UUID(data.recommendation_id)
        redacted_text = sanitize_feedback_text(data.text)
        created_at = datetime.now(UTC)

        safety_review_id: uuid.UUID | None = None
        if is_safety_critical_feedback(data.category):
            safety_review_id = uuid.uuid4()
            severity = "EXTREME" if data.category == "UNSAFE" else "SEVERE"
            review_entry = SafetyReviewQueueModel(
                id=safety_review_id,
                feedback_id=feedback_id,
                severity=severity,
                status="NEW",
                created_at=created_at,
            )
            self.session.add(review_entry)
            SAFETY_REVIEW_QUEUE_SIZE.labels(status="NEW").inc()

        feedback_entry = FeedbackModel(
            id=feedback_id,
            user_id=user_uuid,
            recommendation_id=rec_uuid,
            category=data.category,
            text_redacted=redacted_text,
            review_status="NEW",
            safety_review_id=safety_review_id,
            created_at=created_at,
        )
        self.session.add(feedback_entry)
        await self.session.commit()

        FEEDBACK_SUBMISSIONS_TOTAL.labels(category=data.category).inc()

        return FeedbackEvent(
            feedback_id=str(feedback_id),
            recommendation_id=str(rec_uuid),
            category=data.category,
            text_redacted=redacted_text,
            review_status="NEW",
            safety_review_id=str(safety_review_id) if safety_review_id else None,
            created_at=created_at,
        )

    async def list_safety_reviews(
        self,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SafetyReviewItem], int]:
        query = select(SafetyReviewQueueModel)
        count_query = select(func.count(SafetyReviewQueueModel.id))

        if status:
            query = query.where(SafetyReviewQueueModel.status == status)
            count_query = count_query.where(SafetyReviewQueueModel.status == status)

        total_res = await self.session.execute(count_query)
        total = total_res.scalar_one()

        offset = (page - 1) * page_size
        query = (
            query.order_by(SafetyReviewQueueModel.created_at.desc()).offset(offset).limit(page_size)
        )
        res = await self.session.execute(query)
        rows = res.scalars().all()

        items = [
            SafetyReviewItem(
                id=str(r.id),
                feedback_id=str(r.feedback_id),
                severity=cast(Any, r.severity),
                status=cast(Any, r.status),
                assigned_to=r.assigned_to,
                notes=r.notes,
                created_at=r.created_at,
                resolved_at=r.resolved_at,
            )
            for r in rows
        ]
        return items, total

    async def transition_safety_review(
        self,
        review_id: uuid.UUID,
        new_status: ReviewStatus,
        assigned_to: str | None = None,
        notes: str | None = None,
    ) -> SafetyReviewItem:
        query = select(SafetyReviewQueueModel).where(SafetyReviewQueueModel.id == review_id)
        res = await self.session.execute(query)
        review = res.scalar_one_or_none()
        if not review:
            raise ValueError(f"Safety review record '{review_id}' not found.")

        current_status = cast(ReviewStatus, review.status)
        allowed = VALID_TRANSITIONS.get(current_status, set())
        if new_status not in allowed and new_status != current_status:
            raise ValueError(
                f"Invalid transition from '{current_status}' to '{new_status}'. Allowed: {allowed}"
            )

        review.status = new_status
        if assigned_to is not None:
            review.assigned_to = assigned_to
        if notes is not None:
            review.notes = notes

        if new_status in ("RESOLVED", "DISMISSED"):
            review.resolved_at = datetime.now(UTC)
        elif current_status in ("RESOLVED", "DISMISSED") and new_status not in (
            "RESOLVED",
            "DISMISSED",
        ):
            review.resolved_at = None

        # Update matching feedback record
        fb_query = select(FeedbackModel).where(FeedbackModel.id == review.feedback_id)
        fb_res = await self.session.execute(fb_query)
        fb = fb_res.scalar_one_or_none()
        if fb:
            fb.review_status = new_status

        await self.session.commit()
        await self.session.refresh(review)

        return SafetyReviewItem(
            id=str(review.id),
            feedback_id=str(review.feedback_id),
            severity=cast(Any, review.severity),
            status=cast(Any, review.status),
            assigned_to=review.assigned_to,
            notes=review.notes,
            created_at=review.created_at,
            resolved_at=review.resolved_at,
        )
