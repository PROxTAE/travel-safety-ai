from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts import RiskAssessment, RouteCandidate
from app.models import RiskAssessmentRecord, RouteEvaluation


async def save_fallback_assessments(
    session: AsyncSession,
    *,
    assessments: list[RiskAssessment],
    input_hash: str,
) -> None:
    session.add_all(
        [
            RiskAssessmentRecord(
                id=assessment.assessment_id,
                snapshot_id=assessment.snapshot_id,
                route_id=assessment.route_id,
                model_version_id=None,
                score=assessment.score,
                probability_high=assessment.probability_high,
                uncertainty=assessment.uncertainty,
                risk_level=assessment.risk_level.value,
                reason_codes=list(assessment.reason_codes),
                safety_overrides=[
                    item.model_dump(mode="json") for item in assessment.safety_overrides
                ],
                quality_json=assessment.quality.model_dump(mode="json"),
                input_hash=input_hash,
            )
            for assessment in assessments
        ]
    )
    await session.commit()


async def save_fallback_route_evaluations(
    session: AsyncSession,
    *,
    snapshot_id: UUID,
    routes: list[RouteCandidate],
    unusable_route_ids: list[UUID],
    policy_version: str,
    input_hash: str,
) -> None:
    unusable = set(unusable_route_ids)
    records = [
        RouteEvaluation(
            snapshot_id=snapshot_id,
            route_id=cast(UUID, route.route_id),
            policy_version=policy_version,
            exposure_score=route.exposure.score if route.exposure is not None else None,
            usable=route.route_id not in unusable,
            hard_constraints=(
                list(route.exposure.hard_constraint_codes) if route.exposure is not None else []
            ),
            tradeoffs_json={"ranking_status": "UNAVAILABLE"},
            source_ids=[str(source.source_id) for source in route.sources],
            input_hash=input_hash,
        )
        for route in routes
    ]
    session.add_all(records)
    await session.commit()
