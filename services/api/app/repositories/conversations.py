"""Repository queries for conversation summaries.

Conversations in this service are projected from the assessment requests that carry a
`conversation_id`. Every query filters by `user_id` so conversations are strictly isolated
to their owner.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.travel import AssessmentRequest
from app.schemas.conversation import ConversationModel


async def list_conversations_for_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[ConversationModel], str | None, int]:
    """List conversation threads for a user, most recently active first."""
    # Subquery / aggregate by conversation_id for the user
    stmt = (
        select(
            AssessmentRequest.conversation_id,
            func.max(cast(AssessmentRequest.trip_id, String)).label("trip_id_str"),
            func.min(AssessmentRequest.created_at).label("created_at"),
            func.max(AssessmentRequest.updated_at).label("updated_at"),
            func.count(AssessmentRequest.id).label("message_count"),
        )
        .where(
            AssessmentRequest.user_id == user_id,
            AssessmentRequest.conversation_id.is_not(None),
        )
        .group_by(AssessmentRequest.conversation_id)
        .order_by(desc("updated_at"), desc(AssessmentRequest.conversation_id))
    )

    result = await session.execute(stmt)
    rows = result.all()

    total = len(rows)
    # Cursor pagination: cursor is ISO timestamp or index
    start_idx = 0
    if cursor is not None:
        try:
            start_idx = int(cursor)
        except ValueError:
            start_idx = 0

    page_rows = rows[start_idx : start_idx + limit]
    next_cursor = str(start_idx + limit) if (start_idx + limit) < total else None

    conversations: list[ConversationModel] = []
    for row in page_rows:
        conv_id = row.conversation_id
        if conv_id is None:
            continue

        # Look up the latest request in this conversation to find recommendation_id
        latest_req_stmt = (
            select(AssessmentRequest.recommendation_id)
            .where(
                AssessmentRequest.user_id == user_id,
                AssessmentRequest.conversation_id == conv_id,
                AssessmentRequest.recommendation_id.is_not(None),
            )
            .order_by(desc(AssessmentRequest.created_at))
            .limit(1)
        )
        latest_rec_res = await session.execute(latest_req_stmt)
        last_rec_id = latest_rec_res.scalar_one_or_none()

        trip_id_val = uuid.UUID(row.trip_id_str) if row.trip_id_str else None

        conversations.append(
            ConversationModel(
                conversation_id=conv_id,
                trip_id=trip_id_val,
                title=f"Chat {str(conv_id)[:8]}",
                last_message_preview=None,
                last_recommendation_id=last_rec_id,
                message_count=row.message_count,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )

    return conversations, next_cursor, total
