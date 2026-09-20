"""Orchestrating one assessment run.

This module holds the sequencing that the routers would otherwise duplicate: normalise the input,
commit the request, call the agent, and afterwards reconcile what the agent reports with what this
service has already told the traveller.

**The commit ordering is the load-bearing part.** The request row is written and committed before
`POST /internal/v1/runs` is attempted. Every other order loses runs. Call-then-write loses the run
whenever the agent answers and this service dies before writing; write-without-commit loses it
whenever the transaction is rolled back by the very failure being handled. Committing first means
the worst case is a row in QUEUED that never started, which is visible, pollable and fixable —
rather than a traveller who was told nothing and has nothing to poll.

**Reconciliation is one-directional.** The agent is the authority on progress; this service is the
authority on what the traveller has been told. `app.domain.run` decides which agent reports are
allowed to change the record, and anything it refuses is dropped rather than applied.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.agent import AgentClient, AgentRejectedRequest
from app.clients.recommendation import RecommendationClient, RecommendationInvalid
from app.db.models.travel import AssessmentRequest, Trip
from app.domain import run as machine
from app.errors.exceptions import DependencyTimeout, DependencyUnavailable
from app.observability.logging import get_logger
from app.repositories import requests as requests_repo
from app.schemas.run import RunRefModel, RunStateModel
from app.services import run_events
from app.settings import Settings

logger = get_logger(__name__)


def events_url(request_id: uuid.UUID) -> str:
    return f"/api/v1/runs/{request_id}/events"


def poll_url(request_id: uuid.UUID) -> str:
    return f"/api/v1/runs/{request_id}"


def result_url(recommendation_id: uuid.UUID) -> str:
    return f"/api/v1/recommendations/{recommendation_id}"


def normalise_input(
    trip: Trip,
    *,
    question: str | None,
    locale: str,
    timezone: str,
    live_location_consent_id: uuid.UUID | None,
    avoid_areas: list[dict[str, Any]],
    contract_version: str,
) -> dict[str, Any]:
    """Build the `TravelRequest` the agent receives.

    The journey comes from the stored trip and never from the request body, so a client cannot
    assess one trip while describing another. Locale and timezone are resolved here, once: the
    agent should not have to decide whose timezone "tomorrow morning" was meant in, and the trip's
    own zone is the only answer that survives the traveller crossing one.
    """
    return {
        "trip_id": str(trip.id),
        "origin": trip.origin,
        "destination": trip.destination,
        "departure_time": trip.departure_time.isoformat(),
        "return_time": trip.return_time.isoformat() if trip.return_time else None,
        "timezone": timezone,
        "travel_modes": list(trip.travel_modes),
        "preferences": dict(trip.preferences or {}),
        "question": question,
        "locale": locale,
        "live_location_consent_id": (
            str(live_location_consent_id) if live_location_consent_id else None
        ),
        "avoid_areas": avoid_areas,
        "contract_version": contract_version,
    }


def input_digest(payload: dict[str, Any]) -> str:
    """A stable digest of the normalised input.

    Stored instead of the input itself. It is enough to recognise a retry and to tell two runs
    apart in an operator view, and it holds nothing about where somebody is going.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def to_ref(row: AssessmentRequest) -> RunRefModel:
    return RunRefModel(
        request_id=row.id,
        trip_id=row.trip_id,
        conversation_id=row.conversation_id,
        status=machine.ensure_known(row.status),
        events_url=events_url(row.id),
        poll_url=poll_url(row.id),
        submitted_at=row.created_at,
    )


def to_state(row: AssessmentRequest) -> RunStateModel:
    """Turn a stored row into the contract entity.

    `model_validate` rather than field-by-field construction, so a column that somehow holds
    something the contract does not allow is caught here and becomes a withheld response rather
    than a malformed one.
    """
    error: dict[str, Any] | None = None
    if row.error_code is not None:
        error = {
            "code": row.error_code,
            "message": row.error_message or "The assessment could not be completed.",
            "field_errors": [],
            # A traveller may retry a dependency failure; they may not usefully retry a rejection.
            "retryable": row.error_code in {"DEPENDENCY_TIMEOUT", "DEPENDENCY_UNAVAILABLE"},
            "retry_after_seconds": None,
        }

    return RunStateModel.model_validate(
        {
            "request_id": row.id,
            "trip_id": row.trip_id,
            "conversation_id": row.conversation_id,
            "status": row.status,
            "stage": row.stage,
            "percent": row.percent,
            "message_key": row.message_key,
            "missing_fields": list(row.missing_fields or []),
            "recommendation_id": row.recommendation_id,
            "result_url": (
                result_url(row.recommendation_id) if row.recommendation_id is not None else None
            ),
            "error": error,
            "degraded_services": list(row.degraded_services or []),
            "submitted_at": row.created_at,
            "updated_at": row.updated_at,
            "completed_at": row.completed_at,
        }
    )


async def announce_accepted(
    redis: Redis, settings: Settings, row: AssessmentRequest, *, correlation_id: str | None
) -> None:
    """Publish `run.accepted`, so a client that connects immediately sees the run exists."""
    await run_events.publish(
        redis,
        settings,
        request_id=row.id,
        event_type="run.accepted",
        payload={
            "request_id": str(row.id),
            "status": row.status,
            "submitted_at": row.created_at.isoformat(),
        },
        correlation_id=correlation_id,
    )


async def announce_terminal(
    redis: Redis, settings: Settings, row: AssessmentRequest, *, correlation_id: str | None
) -> None:
    """Publish the event that closes the stream.

    Only called once the row already holds the terminal state, so the stream and the pollable
    record can never disagree about how a run ended.
    """
    if row.status in {"COMPLETED", "PARTIAL"} and row.recommendation_id is not None:
        await run_events.publish(
            redis,
            settings,
            request_id=row.id,
            event_type="run.completed",
            payload={
                "request_id": str(row.id),
                "recommendation_id": str(row.recommendation_id),
                "result_url": result_url(row.recommendation_id),
                "status": row.status,
            },
            correlation_id=correlation_id,
        )
        return

    state = to_state(row)
    await run_events.publish(
        redis,
        settings,
        request_id=row.id,
        event_type="run.failed",
        payload={
            "request_id": str(row.id),
            "error": (
                state.error.model_dump(mode="json")
                if state.error is not None
                else {
                    "code": "INTERNAL_ERROR",
                    "message": "The assessment could not be completed.",
                    "field_errors": [],
                    "retryable": False,
                    "retry_after_seconds": None,
                }
            ),
        },
        correlation_id=correlation_id,
    )


async def start(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    row: AssessmentRequest,
    payload: dict[str, Any],
    agent: AgentClient,
    correlation_id: str | None,
) -> AssessmentRequest:
    """Hand an already-committed run to the agent and record what came back.

    Called after the caller has committed `row`. Every failure below leaves the run in a state the
    client can poll, which is the whole reason the commit came first.
    """
    try:
        accepted = await agent.create_run(payload, request_id=str(row.id))
    except AgentRejectedRequest as exc:
        # The agent understood the request and refused it. Retrying would be refused again, so the
        # run ends here rather than being left QUEUED for a poller to keep hoping over.
        requests_repo.advance(
            row,
            status="FAILED",
            error_code="INTERNAL_ERROR",
            error_message="The assessment could not be started.",
        )
        await session.flush()
        logger.error(
            "run_rejected_by_agent",
            event_type="run",
            request_id=str(row.id),
            agent_status=exc.status_code,
            agent_code=exc.code,
        )
        await announce_terminal(redis, settings, row, correlation_id=correlation_id)
        return row
    except (DependencyTimeout, DependencyUnavailable) as exc:
        # Unavailable, not invalid. The run is marked FAILED with a retryable code so the client is
        # told to try again rather than left watching a run that will never move.
        requests_repo.advance(
            row,
            status="FAILED",
            error_code=exc.code.value,
            error_message="The assessment service is unavailable. Nothing was assessed.",
        )
        await session.flush()
        await announce_terminal(redis, settings, row, correlation_id=correlation_id)
        return row

    agent_run_id = accepted.get("request_id") or accepted.get("run_id")
    if isinstance(agent_run_id, str) and agent_run_id:
        await requests_repo.attach_agent_run(session, row=row, agent_run_id=agent_run_id)

    reported = accepted.get("status")
    if isinstance(reported, str) and reported in machine.ALL_STATUSES and reported != "QUEUED":
        requests_repo.advance(row, status=reported)
        await session.flush()

    return row


async def reconcile(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    row: AssessmentRequest,
    agent: AgentClient,
    recommendations: RecommendationClient,
    correlation_id: str | None,
) -> AssessmentRequest:
    """Refresh a run from the agent, applying only what the state machine permits.

    Called by the poll endpoint. A terminal run is returned untouched — it is history, and asking
    the agent about it would at best confirm what is already known and at worst try to reopen it.

    Every failure to reach the agent leaves the stored state alone. A run whose progress cannot be
    refreshed is still a run whose last known progress is true.
    """
    if machine.is_terminal(row.status) or row.agent_run_id is None:
        return row

    try:
        remote = await agent.get_run(row.agent_run_id)
    except (DependencyTimeout, DependencyUnavailable):
        # Report the last known state rather than inventing a newer one.
        logger.info(
            "run_refresh_skipped",
            event_type="run",
            request_id=str(row.id),
            detail="agent unreachable; reporting last known state",
        )
        return row

    if remote is None:
        # The agent has never heard of a run this service committed. That happens when the create
        # call failed after the commit, and it is terminal: nothing is working on this request.
        requests_repo.advance(
            row,
            status="FAILED",
            error_code="DEPENDENCY_UNAVAILABLE",
            error_message="The assessment was never started. Nothing was assessed.",
        )
        await session.flush()
        await announce_terminal(redis, settings, row, correlation_id=correlation_id)
        return row

    raw_status = remote.get("status")
    if not isinstance(raw_status, str) or raw_status not in machine.ALL_STATUSES:
        logger.error(
            "run_unknown_status_from_agent",
            event_type="run",
            request_id=str(row.id),
            detail="version skew between api and agent; state left unchanged",
        )
        return row

    if raw_status in {"COMPLETED", "PARTIAL"}:
        return await _complete(
            session,
            redis,
            settings,
            row=row,
            remote=remote,
            status=raw_status,
            recommendations=recommendations,
            correlation_id=correlation_id,
        )

    moved = requests_repo.advance(
        row,
        status=raw_status,
        stage=_str_or_none(remote.get("stage")),
        percent=_int_or_none(remote.get("percent")),
        message_key=_str_or_none(remote.get("message_key")),
        missing_fields=_str_list(remote.get("missing_fields")),
        error_code=_str_or_none(remote.get("error_code")),
        error_message=_str_or_none(remote.get("error_message")),
        degraded_services=_dict_list(remote.get("degraded_services")),
    )
    if moved:
        await session.flush()
        if machine.is_terminal(row.status):
            await announce_terminal(redis, settings, row, correlation_id=correlation_id)

    return row


async def _complete(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    row: AssessmentRequest,
    remote: dict[str, Any],
    status: str,
    recommendations: RecommendationClient,
    correlation_id: str | None,
) -> AssessmentRequest:
    """Finish a run, but only after the recommendation has been checked.

    This is the gate phase 5 item 5 asks for. The agent saying "done, here is an id" is not enough
    to tell a traveller the assessment succeeded: the object behind that id has to exist, belong to
    this run, and match the contract. Anything else and the run fails instead, because an id that
    leads to something unreadable is worse than no id at all.
    """
    raw_id = remote.get("recommendation_id")
    try:
        recommendation_id = uuid.UUID(str(raw_id))
    except (ValueError, TypeError):
        requests_repo.advance(
            row,
            status="FAILED",
            error_code="INTERNAL_ERROR",
            error_message="The assessment finished without a usable result.",
        )
        await session.flush()
        logger.error(
            "run_completed_without_recommendation", event_type="run", request_id=str(row.id)
        )
        await announce_terminal(redis, settings, row, correlation_id=correlation_id)
        return row

    try:
        await recommendations.fetch_validated(
            recommendation_id, request_id=row.id, trip_id=row.trip_id
        )
    except RecommendationInvalid as exc:
        requests_repo.advance(
            row,
            status="FAILED",
            error_code="POLICY_VALIDATION_FAILED",
            error_message="The assessment result did not pass validation and was not shown.",
        )
        await session.flush()
        logger.error(
            "recommendation_rejected",
            event_type="run",
            request_id=str(row.id),
            reason=exc.reason,
        )
        await announce_terminal(redis, settings, row, correlation_id=correlation_id)
        return row
    except (DependencyTimeout, DependencyUnavailable):
        # Cannot check it yet. The run stays in flight and the next poll tries again — far better
        # than completing on an unverified result or failing a run that may be perfectly good.
        logger.info(
            "recommendation_validation_deferred",
            event_type="run",
            request_id=str(row.id),
            detail="module 08 unreachable; run left in progress",
        )
        return row

    moved = requests_repo.advance(
        row,
        status=status,
        recommendation_id=recommendation_id,
        degraded_services=_dict_list(remote.get("degraded_services")),
    )
    if moved:
        await session.flush()
        await announce_terminal(redis, settings, row, correlation_id=correlation_id)

    return row


async def cancel(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    row: AssessmentRequest,
    agent: AgentClient,
    correlation_id: str | None,
) -> bool:
    """Stop a run. Returns False when it had already finished.

    The record is marked cancelled first and the agent is told afterwards, best effort. The audit
    of what already ran is kept: cancelling abandons the outstanding work, it does not erase the
    fact that the work happened.
    """
    if not requests_repo.advance(row, status="CANCELLED"):
        return False

    row.message_key = "run.cancelled_by_user"
    await session.flush()

    if row.agent_run_id is not None:
        await agent.cancel_run(row.agent_run_id, reason="cancelled_by_user")

    await run_events.publish(
        redis,
        settings,
        request_id=row.id,
        event_type="run.failed",
        payload={
            "request_id": str(row.id),
            "error": {
                "code": "CONFLICT",
                "message": "The assessment was cancelled.",
                "field_errors": [],
                "retryable": False,
                "retry_after_seconds": None,
            },
        },
        correlation_id=correlation_id,
    )
    return True


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)][:64]


def _dict_list(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, dict)][:32]


def utcnow() -> datetime:
    return datetime.now(UTC)
