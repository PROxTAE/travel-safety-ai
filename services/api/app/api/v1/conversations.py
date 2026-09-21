"""Conversations endpoints for the public API.

Serves assistant threads and follow-up turns (module 03 integration).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.responses import data_response, list_response
from app.api.v1.me import TravelPrincipal
from app.auth.dependencies import DbSession
from app.clients.agent import AgentClient
from app.errors.exceptions import IdempotencyConflict, NotFound
from app.observability.logging import get_logger
from app.repositories import (
    audit,
    idempotency,
    user_profiles,
)
from app.repositories import (
    conversations as conv_repo,
)
from app.repositories import (
    requests as requests_repo,
)
from app.repositories import (
    trips as trips_repo,
)
from app.schemas.conversation import (
    ConversationMessageRequest,
    ConversationModel,
)
from app.schemas.envelope import DataResponse, ListResponse, PageMeta
from app.schemas.run import RunRefModel
from app.services import runs as orchestrator

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

POST_MESSAGE_OPERATION = "postConversationMessage"


@router.get(
    "",
    summary="List the caller's recent assistant threads",
    response_model=ListResponse[ConversationModel],
    responses={
        200: {"description": "Conversations, most recently updated first."},
        401: {"description": "Unauthorized."},
    },
)
async def list_conversations(
    request: Request,
    session: DbSession,
    principal: TravelPrincipal,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ListResponse[ConversationModel]:
    """List conversation summaries owned by the authenticated user."""
    items, next_cursor, _ = await conv_repo.list_conversations_for_user(
        session,
        principal.user_id,
        limit=limit,
        cursor=cursor,
    )

    page = PageMeta(cursor=cursor, next_cursor=next_cursor, has_more=bool(next_cursor))
    return list_response(request, items, page=page)


@router.post(
    "/{conversation_id}/messages",
    summary="Ask a follow-up question",
    response_model=DataResponse[RunRefModel],
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "Follow-up accepted."},
        400: {"description": "Validation error."},
        401: {"description": "Unauthorized."},
        404: {"description": "Trip or conversation not found."},
        409: {"description": "Idempotency conflict."},
    },
)
async def post_conversation_message(
    request: Request,
    response: Response,
    session: DbSession,
    principal: TravelPrincipal,
    conversation_id: Annotated[uuid.UUID, Path()],
    payload_body: ConversationMessageRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DataResponse[RunRefModel]:
    """Continue a conversation thread with a new turn and trigger a fresh assessment."""
    trip = None
    trip_id = payload_body.trip_id

    if trip_id is not None:
        trip = await trips_repo.get_owned(session, owner_id=principal.user_id, trip_id=trip_id)
        if trip is None:
            raise NotFound
    else:
        # Check if conversation already has an associated trip from a prior request
        from sqlalchemy import select

        from app.db.models.travel import AssessmentRequest

        stmt = (
            select(AssessmentRequest.trip_id)
            .where(
                AssessmentRequest.user_id == principal.user_id,
                AssessmentRequest.conversation_id == conversation_id,
                AssessmentRequest.trip_id.is_not(None),
            )
            .limit(1)
        )
        res = await session.execute(stmt)
        prior_trip_id = res.scalar_one_or_none()
        if prior_trip_id is not None:
            trip = await trips_repo.get_owned(
                session, owner_id=principal.user_id, trip_id=prior_trip_id
            )
            trip_id = prior_trip_id

    idem_payload = payload_body.model_dump(mode="json")
    if idempotency_key is not None:
        try:
            existing_id = await idempotency.lookup(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=POST_MESSAGE_OPERATION,
                payload=idem_payload,
            )
        except idempotency.KeyConflict:
            raise IdempotencyConflict from None

        if existing_id is not None:
            existing_req = await requests_repo.get_owned(
                session, owner_id=principal.user_id, request_id=existing_id
            )
            if existing_req is not None:
                response.status_code = status.HTTP_200_OK
                response.headers["Location"] = orchestrator.poll_url(existing_req.id)
                return data_response(request, orchestrator.to_ref(existing_req))

    settings = request.app.state.settings
    profile = await user_profiles.get_owned(session, owner_id=principal.user_id)
    locale = payload_body.locale or (profile.locale if profile is not None else "en-US")
    timezone = (
        trip.timezone if trip is not None else (profile.timezone if profile is not None else "UTC")
    )

    if trip is not None:
        agent_payload = orchestrator.normalise_input(
            trip,
            question=payload_body.question,
            locale=locale,
            timezone=timezone,
            live_location_consent_id=None,
            avoid_areas=[],
            contract_version=settings.contract_version,
        )
    else:
        agent_payload = {
            "request_id": str(uuid.uuid4()),
            "conversation_id": str(conversation_id),
            "question": payload_body.question,
            "locale": locale,
            "timezone": timezone,
            "contract_version": settings.contract_version,
        }

    run_row = await requests_repo.create(
        session,
        owner_id=principal.user_id,
        trip_id=trip_id,
        conversation_id=conversation_id,
        input_digest=orchestrator.input_digest(agent_payload),
        contract_version=settings.contract_version,
        locale=locale,
        timezone=timezone,
    )

    if idempotency_key is not None:
        try:
            await idempotency.record(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=POST_MESSAGE_OPERATION,
                payload=idem_payload,
                resource_id=run_row.id,
            )
        except IntegrityError:
            await session.rollback()
            winner_id = await idempotency.lookup(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=POST_MESSAGE_OPERATION,
                payload=idem_payload,
            )
            if winner_id is not None:
                winner = await requests_repo.get_owned(
                    session, owner_id=principal.user_id, request_id=winner_id
                )
                if winner is not None:
                    response.status_code = status.HTTP_200_OK
                    response.headers["Location"] = orchestrator.poll_url(winner.id)
                    return data_response(request, orchestrator.to_ref(winner))

    await audit.write(
        session,
        user_id=principal.user_id,
        action="conversation.post_message",
        resource_type="conversation",
        resource_id=conversation_id,
        details={"request_id": str(run_row.id)},
    )

    if trip is not None:
        trip.latest_request_id = run_row.id

    await session.commit()
    await session.refresh(run_row)

    correlation_id = str(getattr(request.state, "correlation_id", "")) or None
    redis = getattr(request.app.state, "redis", None)

    if redis is not None:
        await orchestrator.announce_accepted(
            redis, settings, run_row, correlation_id=correlation_id
        )

        run_row = await orchestrator.start(
            session,
            redis,
            settings,
            row=run_row,
            payload=agent_payload,
            agent=AgentClient(request.app.state.internal_http, settings),
            correlation_id=correlation_id,
        )
        await session.commit()
        await session.refresh(run_row)

    response.status_code = status.HTTP_202_ACCEPTED
    response.headers["Location"] = orchestrator.poll_url(run_row.id)
    response.headers["Cache-Control"] = "no-store"

    return data_response(request, orchestrator.to_ref(run_row))
