"""Feedback and alert subscription endpoints.

Proxies explicit user feedback and trip alert subscriptions to module 08 with consent
and ownership checks.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.responses import data_response
from app.api.v1.me import TravelPrincipal
from app.auth.dependencies import DbSession
from app.clients.recommendation import RecommendationClient
from app.db.models.identity import Consent
from app.db.models.travel import AssessmentRequest
from app.domain import trip as rules
from app.errors.exceptions import Forbidden, IdempotencyConflict, NotFound
from app.observability.logging import get_logger
from app.repositories import audit, idempotency
from app.repositories import trips as trips_repo
from app.schemas.envelope import DataResponse
from app.schemas.feedback import (
    AlertSubscriptionModel,
    CreateAlertSubscriptionRequest,
    FeedbackEventModel,
    FeedbackRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["feedback"])

CREATE_FEEDBACK_OPERATION = "createFeedback"
CREATE_ALERT_SUB_OPERATION = "createAlertSubscription"

# PII regex patterns for redacting user feedback before storage
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")
COORD_REGEX = re.compile(r"\b-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}\b")


def _redact_sensitive_text(text: str | None) -> str | None:
    """Strip potential phone numbers, emails, and high-precision coordinates."""
    if text is None:
        return None
    redacted = EMAIL_REGEX.sub("[REDACTED EMAIL]", text)
    redacted = PHONE_REGEX.sub("[REDACTED PHONE]", redacted)
    redacted = COORD_REGEX.sub("[REDACTED COORD]", redacted)
    return redacted


def _get_recommendation_client(request: Request) -> RecommendationClient:
    return RecommendationClient(request.app.state.internal_http, request.app.state.settings)


@router.post(
    "/feedback",
    summary="Submit explicit feedback on a recommendation",
    response_model=DataResponse[FeedbackEventModel],
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Feedback stored."},
        400: {"description": "Validation error."},
        401: {"description": "Unauthorized."},
        404: {"description": "Recommendation not found or not owned by caller."},
        409: {"description": "Idempotency conflict."},
    },
)
async def create_feedback(
    request: Request,
    response: Response,
    principal: TravelPrincipal,
    session: DbSession,
    client: Annotated[RecommendationClient, Depends(_get_recommendation_client)],
    payload_body: FeedbackRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DataResponse[FeedbackEventModel]:
    """Submit explicit feedback on a recommendation."""
    # Enforce recommendation ownership
    rec_stmt = (
        select(AssessmentRequest)
        .where(
            AssessmentRequest.user_id == principal.user_id,
            AssessmentRequest.recommendation_id == payload_body.recommendation_id,
        )
        .limit(1)
    )
    rec_res = await session.execute(rec_stmt)
    req_row = rec_res.scalar_one_or_none()
    if req_row is None:
        raise NotFound

    idem_payload = payload_body.model_dump(mode="json")
    if idempotency_key is not None:
        try:
            existing_id = await idempotency.lookup(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=CREATE_FEEDBACK_OPERATION,
                payload=idem_payload,
            )
        except idempotency.KeyConflict:
            raise IdempotencyConflict from None

        if existing_id is not None:
            response.status_code = status.HTTP_200_OK
            return data_response(
                request,
                FeedbackEventModel(
                    feedback_id=existing_id,
                    recommendation_id=payload_body.recommendation_id,
                    category=payload_body.category,
                    text_redacted=_redact_sensitive_text(payload_body.text),
                    review_status="NEW",
                    created_at=rules.now_utc(),
                ),
            )

    feedback_id = uuid.uuid4()
    sanitized_text = _redact_sensitive_text(payload_body.text)
    now = rules.now_utc()

    # Forward to module 08
    await client.create_feedback(
        feedback_id=feedback_id,
        recommendation_id=payload_body.recommendation_id,
        category=payload_body.category,
        text=sanitized_text,
        idempotency_key=idempotency_key,
    )

    if idempotency_key is not None:
        try:
            await idempotency.record(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=CREATE_FEEDBACK_OPERATION,
                payload=idem_payload,
                resource_id=feedback_id,
            )
        except IntegrityError:
            await session.rollback()

    await audit.write(
        session,
        user_id=principal.user_id,
        action="feedback.create",
        resource_type="feedback",
        resource_id=feedback_id,
        details={
            "recommendation_id": str(payload_body.recommendation_id),
            "category": payload_body.category,
        },
    )
    await session.commit()

    return data_response(
        request,
        FeedbackEventModel(
            feedback_id=feedback_id,
            recommendation_id=payload_body.recommendation_id,
            category=payload_body.category,
            text_redacted=sanitized_text,
            review_status="NEW",
            created_at=now,
        ),
    )


@router.post(
    "/alert-subscriptions",
    summary="Opt in to live alerts for a trip",
    response_model=DataResponse[AlertSubscriptionModel],
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Subscription created."},
        400: {"description": "Validation error."},
        401: {"description": "Unauthorized."},
        403: {"description": "Required ALERT_NOTIFICATION consent missing or revoked."},
        404: {"description": "Trip not found or not owned by caller."},
        409: {"description": "Idempotency conflict."},
    },
)
async def create_alert_subscription(
    request: Request,
    response: Response,
    principal: TravelPrincipal,
    session: DbSession,
    client: Annotated[RecommendationClient, Depends(_get_recommendation_client)],
    payload_body: CreateAlertSubscriptionRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DataResponse[AlertSubscriptionModel]:
    """Register an alert subscription for a trip."""
    # Verify trip ownership
    trip = await trips_repo.get_owned(
        session, owner_id=principal.user_id, trip_id=payload_body.trip_id
    )
    if trip is None:
        raise NotFound

    # Verify active ALERT_NOTIFICATION consent
    now = rules.now_utc()
    stmt = (
        select(Consent)
        .where(
            Consent.id == payload_body.consent_id,
            Consent.user_id == principal.user_id,
            Consent.type == "ALERT_NOTIFICATION",
            Consent.granted.is_(True),
            Consent.revoked_at.is_(None),
            or_(Consent.expires_at.is_(None), Consent.expires_at > now),
        )
        .limit(1)
    )
    res = await session.execute(stmt)
    consent = res.scalar_one_or_none()
    if consent is None:
        raise Forbidden("The required ALERT_NOTIFICATION consent is missing, revoked or expired.")

    idem_payload = payload_body.model_dump(mode="json")
    if idempotency_key is not None:
        try:
            existing_id = await idempotency.lookup(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=CREATE_ALERT_SUB_OPERATION,
                payload=idem_payload,
            )
        except idempotency.KeyConflict:
            raise IdempotencyConflict from None

        if existing_id is not None:
            response.status_code = status.HTTP_200_OK
            return data_response(
                request,
                AlertSubscriptionModel(
                    subscription_id=existing_id,
                    trip_id=payload_body.trip_id,
                    channel=payload_body.channel,
                    consent_id=payload_body.consent_id,
                    min_severity=payload_body.min_severity,
                    status="ACTIVE",
                    created_at=now,
                ),
            )

    subscription_id = uuid.uuid4()

    # Forward to module 08
    await client.create_alert_subscription(
        subscription_id=subscription_id,
        trip_id=payload_body.trip_id,
        channel=payload_body.channel,
        consent_id=payload_body.consent_id,
        min_severity=payload_body.min_severity,
        idempotency_key=idempotency_key,
    )

    if idempotency_key is not None:
        try:
            await idempotency.record(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=CREATE_ALERT_SUB_OPERATION,
                payload=idem_payload,
                resource_id=subscription_id,
            )
        except IntegrityError:
            await session.rollback()

    await audit.write(
        session,
        user_id=principal.user_id,
        action="alert_subscription.create",
        resource_type="alert_subscription",
        resource_id=subscription_id,
        details={"trip_id": str(payload_body.trip_id), "channel": payload_body.channel},
    )
    await session.commit()

    return data_response(
        request,
        AlertSubscriptionModel(
            subscription_id=subscription_id,
            trip_id=payload_body.trip_id,
            channel=payload_body.channel,
            consent_id=payload_body.consent_id,
            min_severity=payload_body.min_severity,
            status="ACTIVE",
            created_at=now,
        ),
    )


@router.delete(
    "/alert-subscriptions/{subscription_id}",
    summary="Opt out of live alerts",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Subscription cancelled. Delivery stops immediately."},
        401: {"description": "Unauthorized."},
        404: {"description": "Subscription not found."},
    },
)
async def delete_alert_subscription(
    request: Request,
    principal: TravelPrincipal,
    session: DbSession,
    client: Annotated[RecommendationClient, Depends(_get_recommendation_client)],
    subscription_id: Annotated[uuid.UUID, Path()],
) -> Response:
    """Cancel an alert subscription."""
    await client.delete_alert_subscription(subscription_id)

    await audit.write(
        session,
        user_id=principal.user_id,
        action="alert_subscription.delete",
        resource_type="alert_subscription",
        resource_id=subscription_id,
        details={},
    )
    await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
