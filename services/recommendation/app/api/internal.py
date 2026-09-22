from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.builders.recommendation_builder import PolicyValidationError, RecommendationBuilder
from app.database import get_db
from app.directory.resolver import resolve_emergency_contacts
from app.domain.alerts import DeliveryChannel, SeverityLevel
from app.domain.feedback import FeedbackCategory, FeedbackCreate, ReviewStatus
from app.domain.recommendation import RecommendationResponse
from app.repositories.feedback_repo import FeedbackRepository
from app.repositories.recommendation_repo import RecommendationRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.settings import get_settings
from app.workers.deliver_alerts import AlertDeliveryService

router = APIRouter(prefix="/internal/v1")


def get_meta_envelope(
    request_id: str | None = None,
    correlation_id: str | None = None,
    degraded_services: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request_id or str(uuid.uuid4()),
        "correlation_id": correlation_id or str(uuid.uuid4()),
        "contract_version": get_settings().CONTRACT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "degraded_services": degraded_services or [],
    }


def verify_service_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    settings = get_settings()
    expected = settings.INTERNAL_SERVICE_TOKEN
    if not expected:
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "AUTHENTICATION_REQUIRED",
                    "message": "Service token required in production",
                },
            )
        # If no internal service token configured in dev mode, allow
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTHENTICATION_REQUIRED", "message": "Missing Bearer token"},
        )
    token = authorization.split("Bearer ", 1)[1].strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "FORBIDDEN", "message": "Invalid internal service token"},
        )


# Request Models


class RecommendationCreateBody(BaseModel):
    request_id: str
    trip_id: str
    conversation_id: str | None = None
    decision: dict[str, Any]
    context: dict[str, Any]
    locale: str = "th-TH"


class FeedbackCreateBody(BaseModel):
    user_id: str
    recommendation_id: str
    category: FeedbackCategory
    text: str | None = None


class SafetyReviewTransitionBody(BaseModel):
    status: ReviewStatus
    assigned_to: str | None = None
    notes: str | None = None


class SubscriptionCreateBody(BaseModel):
    user_id: str
    trip_id: str
    consent_id: str
    channel: DeliveryChannel
    destination: str | None = None
    min_severity: SeverityLevel = "MODERATE"
    expires_at: datetime | None = None


class AlertEvaluationBody(BaseModel):
    trip_id: str
    previous_recommendation: dict[str, Any] | None = None
    new_recommendation: dict[str, Any]
    force_delivery: bool = False


# Endpoints


@router.post("/recommendations", status_code=status.HTTP_201_CREATED)
async def create_recommendation(
    body: RecommendationCreateBody,
    response: Response,
    x_request_id: str = Header(default_factory=lambda: str(uuid.uuid4()), alias="X-Request-ID"),
    x_correlation_id: str = Header(
        default_factory=lambda: str(uuid.uuid4()), alias="X-Correlation-ID"
    ),
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = RecommendationRepository(db)

    # Check for idempotent replay by request_id
    try:
        req_uuid = uuid.UUID(body.request_id)
        existing = await repo.get_by_request_id(req_uuid)
        if existing:
            response.status_code = status.HTTP_200_OK
            return {
                "data": existing.response_json,
                "meta": get_meta_envelope(x_request_id, x_correlation_id),
            }
    except ValueError:
        pass

    builder = RecommendationBuilder(db)
    try:
        recommendation_obj = await builder.build_recommendation(
            request_id=body.request_id,
            trip_id=body.trip_id,
            decision=body.decision,
            context=body.context,
            conversation_id=body.conversation_id,
            locale=body.locale,
        )
    except PolicyValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "POLICY_VALIDATION_FAILED", "message": str(e)},
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        ) from e

    await repo.save_recommendation(recommendation_obj)

    return {
        "data": recommendation_obj.model_dump(mode="json"),
        "meta": get_meta_envelope(
            x_request_id,
            x_correlation_id,
            degraded_services=[ds.model_dump() for ds in recommendation_obj.degraded_services],
        ),
    }


@router.get("/recommendations/{recommendation_id}")
async def get_recommendation(
    recommendation_id: str,
    x_request_id: str = Header(default_factory=lambda: str(uuid.uuid4()), alias="X-Request-ID"),
    x_correlation_id: str = Header(
        default_factory=lambda: str(uuid.uuid4()), alias="X-Correlation-ID"
    ),
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        rec_uuid = uuid.UUID(recommendation_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "Invalid UUID format"},
        ) from e

    repo = RecommendationRepository(db)
    rec = await repo.get_by_id(rec_uuid)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": f"Recommendation '{recommendation_id}' not found.",
            },
        )

    return {
        "data": rec.response_json,
        "meta": get_meta_envelope(x_request_id, x_correlation_id),
    }


@router.get("/emergency/contacts")
async def get_emergency_contacts(
    country_code: str = Query(..., min_length=2, max_length=2),
    subdivision: str | None = Query(default=None),
    service_type: str | None = Query(default=None),
    locale: str = Query(default="th-TH"),
    x_request_id: str = Header(default_factory=lambda: str(uuid.uuid4()), alias="X-Request-ID"),
    x_correlation_id: str = Header(
        default_factory=lambda: str(uuid.uuid4()), alias="X-Correlation-ID"
    ),
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    contacts = await resolve_emergency_contacts(
        country_code=country_code,
        subdivision=subdivision,
        service_type=service_type,
        locale=locale,
        session=db,
    )
    return {
        "data": [c.model_dump(mode="json") for c in contacts],
        "meta": get_meta_envelope(x_request_id, x_correlation_id),
    }


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    body: FeedbackCreateBody,
    x_request_id: str = Header(default_factory=lambda: str(uuid.uuid4()), alias="X-Request-ID"),
    x_correlation_id: str = Header(
        default_factory=lambda: str(uuid.uuid4()), alias="X-Correlation-ID"
    ),
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = FeedbackRepository(db)
    event = await repo.create_feedback(
        FeedbackCreate(
            user_id=body.user_id,
            recommendation_id=body.recommendation_id,
            category=body.category,
            text=body.text,
        )
    )
    return {
        "data": event.model_dump(mode="json"),
        "meta": get_meta_envelope(x_request_id, x_correlation_id),
    }


@router.get("/feedback/safety-review")
async def list_safety_reviews(
    status: ReviewStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    x_request_id: str = Header(default_factory=lambda: str(uuid.uuid4()), alias="X-Request-ID"),
    x_correlation_id: str = Header(
        default_factory=lambda: str(uuid.uuid4()), alias="X-Correlation-ID"
    ),
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = FeedbackRepository(db)
    items, total = await repo.list_safety_reviews(
        status=status,
        page=page,
        page_size=page_size,
    )
    return {
        "data": [item.model_dump(mode="json") for item in items],
        "meta": get_meta_envelope(x_request_id, x_correlation_id),
        "page": {
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    }


@router.post("/feedback/safety-review/{review_id}/transition")
async def transition_safety_review(
    review_id: str,
    body: SafetyReviewTransitionBody,
    x_request_id: str = Header(default_factory=lambda: str(uuid.uuid4()), alias="X-Request-ID"),
    x_correlation_id: str = Header(
        default_factory=lambda: str(uuid.uuid4()), alias="X-Correlation-ID"
    ),
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        rid = uuid.UUID(review_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "Invalid review ID format"},
        ) from e

    repo = FeedbackRepository(db)
    try:
        updated = await repo.transition_safety_review(
            review_id=rid,
            new_status=body.status,
            assigned_to=body.assigned_to,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": str(e)},
        ) from e

    return {
        "data": updated.model_dump(mode="json"),
        "meta": get_meta_envelope(x_request_id, x_correlation_id),
    }


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: SubscriptionCreateBody,
    x_request_id: str = Header(default_factory=lambda: str(uuid.uuid4()), alias="X-Request-ID"),
    x_correlation_id: str = Header(
        default_factory=lambda: str(uuid.uuid4()), alias="X-Correlation-ID"
    ),
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = SubscriptionRepository(db)
    sub = await repo.create_subscription(
        user_id=body.user_id,
        trip_id=body.trip_id,
        consent_id=body.consent_id,
        channel=body.channel,
        destination=body.destination,
        min_severity=body.min_severity,
        expires_at=body.expires_at,
    )
    return {
        "data": sub.model_dump(mode="json"),
        "meta": get_meta_envelope(x_request_id, x_correlation_id),
    }


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_id: str,
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        sid = uuid.UUID(subscription_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "Invalid subscription ID format"},
        ) from e

    repo = SubscriptionRepository(db)
    success = await repo.cancel_subscription(sid)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": f"Subscription '{subscription_id}' not found."},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/alerts/evaluate")
async def evaluate_alerts(
    body: AlertEvaluationBody,
    x_request_id: str = Header(default_factory=lambda: str(uuid.uuid4()), alias="X-Request-ID"),
    x_correlation_id: str = Header(
        default_factory=lambda: str(uuid.uuid4()), alias="X-Correlation-ID"
    ),
    _: None = Depends(verify_service_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    prev_rec = (
        RecommendationResponse(**body.previous_recommendation)
        if body.previous_recommendation
        else None
    )
    new_rec = RecommendationResponse(**body.new_recommendation)

    service = AlertDeliveryService(db)
    result = await service.evaluate_and_deliver(
        trip_id=body.trip_id,
        previous_rec=prev_rec,
        new_rec=new_rec,
        force_delivery=body.force_delivery,
    )

    return {
        "data": result,
        "meta": get_meta_envelope(x_request_id, x_correlation_id),
    }
