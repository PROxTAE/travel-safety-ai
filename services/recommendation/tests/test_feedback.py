from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli.export_feedback import export_feedback_dataset, pseudonymize_id
from app.domain.feedback import FeedbackCreate, sanitize_feedback_text
from app.repositories.feedback_repo import FeedbackRepository


def test_sanitize_feedback_text() -> None:
    raw = "Found accident at [100.5018, 13.7563], call me at 081-234-5678 or john.doe@example.com"
    redacted = sanitize_feedback_text(raw)
    assert redacted is not None
    assert "081-234-5678" not in redacted
    assert "john.doe@example.com" not in redacted
    assert "[100.5018, 13.7563]" not in redacted
    assert "[PHONE_REDACTED]" in redacted
    assert "[EMAIL_REDACTED]" in redacted
    assert "[COORD_REDACTED]" in redacted


@pytest.mark.asyncio
async def test_feedback_helpful_creation(test_db_session: AsyncSession) -> None:
    repo = FeedbackRepository(test_db_session)
    user_id = str(uuid.uuid4())
    rec_id = str(uuid.uuid4())

    event = await repo.create_feedback(
        FeedbackCreate(
            user_id=user_id,
            recommendation_id=rec_id,
            category="HELPFUL",
            text="The safer route was great and clear!",
        )
    )

    assert event.feedback_id is not None
    assert event.category == "HELPFUL"
    assert event.review_status == "NEW"
    assert event.safety_review_id is None


@pytest.mark.asyncio
async def test_feedback_unsafe_routes_to_safety_review_queue(
    test_db_session: AsyncSession,
) -> None:
    repo = FeedbackRepository(test_db_session)
    user_id = str(uuid.uuid4())
    rec_id = str(uuid.uuid4())

    event = await repo.create_feedback(
        FeedbackCreate(
            user_id=user_id,
            recommendation_id=rec_id,
            category="UNSAFE",
            text="Bridge collapsed and road is impassable! Danger!",
        )
    )

    assert event.feedback_id is not None
    assert event.category == "UNSAFE"
    assert event.safety_review_id is not None

    items, total = await repo.list_safety_reviews(status="NEW")
    assert total >= 1
    assert any(item.feedback_id == event.feedback_id for item in items)


@pytest.mark.asyncio
async def test_safety_review_state_transitions(test_db_session: AsyncSession) -> None:
    repo = FeedbackRepository(test_db_session)
    event = await repo.create_feedback(
        FeedbackCreate(
            user_id=str(uuid.uuid4()),
            recommendation_id=str(uuid.uuid4()),
            category="UNSAFE",
            text="Flooded road",
        )
    )
    assert event.safety_review_id is not None
    review_uuid = uuid.UUID(event.safety_review_id)

    # 1. NEW -> TRIAGED
    triaged = await repo.transition_safety_review(
        review_id=review_uuid,
        new_status="TRIAGED",
        assigned_to="safety-operator-1",
    )
    assert triaged.status == "TRIAGED"
    assert triaged.assigned_to == "safety-operator-1"

    # 2. TRIAGED -> IN_REVIEW
    in_review = await repo.transition_safety_review(
        review_id=review_uuid,
        new_status="IN_REVIEW",
        notes="Investigating with provincial road authority",
    )
    assert in_review.status == "IN_REVIEW"

    # 3. IN_REVIEW -> RESOLVED
    resolved = await repo.transition_safety_review(
        review_id=review_uuid,
        new_status="RESOLVED",
        notes="Confirmed hazard closed by authorities.",
    )
    assert resolved.status == "RESOLVED"
    assert resolved.resolved_at is not None


@pytest.mark.asyncio
async def test_pseudonymize_and_export_feedback(test_db_session: AsyncSession) -> None:
    user_id = "d3e05fd1-e122-41c9-80de-e4802a19f7d4"
    pseudo = pseudonymize_id(user_id)
    assert pseudo != user_id
    assert len(pseudo) == 16

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        export_path = tf.name

    try:
        # Export with session should succeed
        code = await export_feedback_dataset(export_path, session=test_db_session)
        assert code == 0
        assert Path(export_path).exists()
    finally:
        Path(export_path).unlink(missing_ok=True)
