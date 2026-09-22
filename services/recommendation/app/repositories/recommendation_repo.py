from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.recommendation import RecommendationResponse
from app.models import RecommendationModel


class RecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_recommendation(
        self,
        recommendation: RecommendationResponse,
    ) -> RecommendationModel:
        db_model = RecommendationModel(
            id=uuid.UUID(recommendation.recommendation_id),
            request_id=uuid.UUID(recommendation.request_id),
            trip_id=uuid.UUID(recommendation.trip_id),
            decision_id=uuid.UUID(recommendation.decision_id)
            if recommendation.decision_id
            else None,
            snapshot_id=uuid.UUID(recommendation.snapshot_id)
            if recommendation.snapshot_id
            else None,
            conversation_id=uuid.UUID(recommendation.conversation_id)
            if recommendation.conversation_id
            else None,
            status=recommendation.status,
            action_code=recommendation.action_code,
            risk_level=recommendation.risk_level,
            confidence=recommendation.confidence,
            response_json=recommendation.model_dump(mode="json"),
            expires_at=recommendation.expires_at,
            created_at=recommendation.created_at,
        )
        self.session.add(db_model)
        await self.session.commit()
        await self.session.refresh(db_model)
        return db_model

    async def get_by_id(self, recommendation_id: uuid.UUID) -> RecommendationModel | None:
        query = select(RecommendationModel).where(RecommendationModel.id == recommendation_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_request_id(self, request_id: uuid.UUID) -> RecommendationModel | None:
        query = (
            select(RecommendationModel)
            .where(RecommendationModel.request_id == request_id)
            .order_by(RecommendationModel.created_at.desc())
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
