"""Recommendation endpoints for the public API.

Serves finished safety verdicts after revalidating them against the contract schema.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy import select

from app.api.responses import data_response
from app.api.v1.me import TravelPrincipal
from app.auth.dependencies import DbSession
from app.clients.recommendation import (
    RecommendationClient,
    RecommendationInvalid,
)
from app.db.models.travel import AssessmentRequest
from app.errors.exceptions import DependencyUnavailable, NotFound
from app.observability.logging import get_logger
from app.schemas.envelope import DataResponse
from app.schemas.recommendation import RecommendationResponseModel

logger = get_logger(__name__)

router = APIRouter(tags=["recommendations"])


def _get_recommendation_client(request: Request) -> RecommendationClient:
    return RecommendationClient(request.app.state.internal_http, request.app.state.settings)


@router.get(
    "/api/v1/recommendations/{recommendation_id}",
    response_model=DataResponse[RecommendationResponseModel],
    summary="Get a finished assessment result",
    description=(
        "The API revalidates the stored response against the contract schema before returning it. "
        "A result that no longer validates is reported as an error rather than rendered."
    ),
    responses={
        200: {"description": "The recommendation."},
        401: {"description": "Unauthorized."},
        404: {"description": "Recommendation not found or not owned by caller."},
        502: {"description": "The stored response failed contract validation and was withheld."},
    },
)
async def get_recommendation(
    request: Request,
    recommendation_id: Annotated[uuid.UUID, Path(description="Recommendation ID")],
    principal: TravelPrincipal,
    session: DbSession,
    client: Annotated[RecommendationClient, Depends(_get_recommendation_client)],
) -> DataResponse[RecommendationResponseModel]:
    """Read a finished recommendation and revalidate against the contract schema."""
    # Ensure recommendation belongs to an assessment run owned by this caller
    stmt = (
        select(AssessmentRequest)
        .where(
            AssessmentRequest.user_id == principal.user_id,
            AssessmentRequest.recommendation_id == recommendation_id,
        )
        .limit(1)
    )
    res = await session.execute(stmt)
    req_row = res.scalar_one_or_none()
    if req_row is None:
        raise NotFound

    try:
        recommendation: RecommendationResponseModel = await client.fetch_validated(
            recommendation_id,
            request_id=req_row.id,
            trip_id=req_row.trip_id,
        )
    except RecommendationInvalid as exc:
        logger.error(
            "recommendation_validation_failed_at_edge",
            recommendation_id=str(recommendation_id),
            reason=exc.reason,
        )
        raise DependencyUnavailable(
            "recommendation",
            message="The assessment result failed contract validation and was withheld.",
        ) from exc

    return data_response(
        request,
        recommendation,
        degraded_services=list(recommendation.degraded_services),
    )
