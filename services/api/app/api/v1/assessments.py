"""Starting an assessment for a trip.

One route, and the ordering inside it is the whole design.

**The request row is committed before the agent is called.** Not flushed — committed, in its own
transaction, so that the row survives whatever happens next. Every other order loses runs: calling
first and writing afterwards loses the run if this process dies between the two, and writing
without committing loses it to the rollback triggered by the very failure being handled. Committing
first means the worst case is a run that exists and failed, which a traveller can see and retry,
instead of a request that vanished.

**The journey comes from the stored trip.** The body carries a question, a locale and areas to
avoid — never an origin or a destination. A client cannot assess one trip while describing another,
because the trip is loaded by id, owner-scoped, and normalised here.

**`Idempotency-Key` is honoured against the same table trips use.** A retry after a network timeout
returns the run the first attempt started rather than starting a second assessment, which would
cost a second set of provider calls and could reach a different verdict from the same question.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.responses import data_response
from app.api.v1.me import TravelPrincipal
from app.auth.dependencies import DbSession
from app.clients.agent import AgentClient
from app.errors.codes import FieldErrorCode
from app.errors.exceptions import FieldError, IdempotencyConflict, NotFound, ValidationFailed
from app.observability.logging import get_logger
from app.repositories import (
    audit,
    idempotency,
    trips,
    user_profiles,
)
from app.repositories import (
    requests as requests_repo,
)
from app.schemas.envelope import DataResponse
from app.schemas.run import CreateAssessmentRequest, RunRefModel
from app.security.rate_limit import rate_limit
from app.services import runs as orchestrator

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/trips", tags=["assessments"])

CREATE_ASSESSMENT_OPERATION = "createAssessment"

ACTION_ASSESSMENT_STARTED = "ASSESSMENT_STARTED"

#: Used only when a profile row is somehow absent. The column has a default, so this is a floor,
#: not a policy: an assessment is not worth refusing over a missing display preference.
FALLBACK_LOCALE = "en-US"


@router.post(
    "/{trip_id}/assessments",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DataResponse[RunRefModel],
    summary="Start a safety assessment for this trip",
    dependencies=[Depends(rate_limit("assessments_create"))],
)
async def create_assessment(
    request: Request,
    response: Response,
    trip_id: Annotated[uuid.UUID, Path(description="The trip to assess.")],
    session: DbSession,
    principal: TravelPrincipal,
    body: CreateAssessmentRequest | None = None,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)
    ] = None,
) -> DataResponse[RunRefModel]:
    """Accept the work and return immediately.

    202, never 200: nothing has been assessed when this returns. The response carries the two URLs
    the client follows — the stream and the poll — and the run itself proceeds asynchronously.
    """
    payload_body = body or CreateAssessmentRequest()

    trip = await trips.get_owned(session, owner_id=principal.user_id, trip_id=trip_id)
    if trip is None:
        raise NotFound("trip")

    settings = request.app.state.settings

    # Resolve locale and timezone once, here. The agent should not have to work out whose timezone
    # "tomorrow morning" meant, and the trip's own zone is the only answer that survives the
    # traveller crossing one. The request may override the locale for this run — a person reading
    # in one language can ask for an answer in another — but the profile is the default.
    profile = await user_profiles.get_owned(session, owner_id=principal.user_id)
    locale = payload_body.locale or (profile.locale if profile is not None else FALLBACK_LOCALE)
    timezone = trip.timezone

    agent_payload = orchestrator.normalise_input(
        trip,
        question=payload_body.question,
        locale=locale,
        timezone=timezone,
        live_location_consent_id=payload_body.live_location_consent_id,
        avoid_areas=list(payload_body.avoid_areas),
        contract_version=settings.contract_version,
    )

    idem_payload = payload_body.model_dump(mode="json")

    if idempotency_key is not None:
        try:
            existing_id = await idempotency.lookup(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=CREATE_ASSESSMENT_OPERATION,
                payload=idem_payload,
            )
        except idempotency.KeyConflict:
            raise IdempotencyConflict from None

        if existing_id is not None:
            existing = await requests_repo.get_owned(
                session, owner_id=principal.user_id, request_id=existing_id
            )
            if existing is not None:
                # The retry of a request that did succeed. Same run, same urls, 200 rather than
                # 202 because nothing new was accepted.
                response.status_code = status.HTTP_200_OK
                response.headers["Location"] = orchestrator.poll_url(existing.id)
                return data_response(request, orchestrator.to_ref(existing))

    if payload_body.conversation_id is not None and payload_body.question is None:
        raise ValidationFailed(
            field_errors=[
                FieldError(
                    path="question",
                    code=FieldErrorCode.REQUIRED,
                    message="Continuing a conversation needs something to continue it with.",
                )
            ]
        )

    row = await requests_repo.create(
        session,
        owner_id=principal.user_id,
        trip_id=trip.id,
        conversation_id=payload_body.conversation_id,
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
                operation=CREATE_ASSESSMENT_OPERATION,
                payload=idem_payload,
                resource_id=row.id,
            )
        except IntegrityError:
            # Another request holding the same key won the race. Roll back this run and return
            # what the winner started, which is what the client would have got had its two
            # attempts not overlapped.
            await session.rollback()
            winner_id = await idempotency.lookup(
                session,
                owner_id=principal.user_id,
                key=idempotency_key,
                operation=CREATE_ASSESSMENT_OPERATION,
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
            raise IdempotencyConflict from None

    # The audit records that an assessment was started, its trip and its locale. Not the question:
    # the audit trail exists to show what the system did, not to keep a second copy of what a
    # person typed.
    await audit.write(
        session,
        user_id=principal.user_id,
        action=ACTION_ASSESSMENT_STARTED,
        resource_type="request",
        resource_id=row.id,
        details={
            "trip_id": str(trip.id),
            "locale": locale,
            "has_question": payload_body.question is not None,
            "avoid_area_count": len(payload_body.avoid_areas),
        },
    )

    trip.latest_request_id = row.id

    # The commit that makes the run durable. Everything after this point can fail without losing
    # the request.
    await session.commit()
    await session.refresh(row)

    correlation_id = str(getattr(request.state, "correlation_id", "")) or None
    redis = request.app.state.redis

    await orchestrator.announce_accepted(redis, settings, row, correlation_id=correlation_id)

    row = await orchestrator.start(
        session,
        redis,
        settings,
        row=row,
        payload=agent_payload,
        agent=AgentClient(request.app.state.internal_http, settings),
        correlation_id=correlation_id,
    )
    await session.commit()
    await session.refresh(row)

    # 202 even when the agent refused, because the run exists either way and its state is what the
    # client polls for. Returning 503 here would leave a committed run nobody told the client
    # about, and the client would have no id with which to find it.
    response.headers["Location"] = orchestrator.poll_url(row.id)
    response.headers["Cache-Control"] = "no-store"
    return data_response(request, orchestrator.to_ref(row))
