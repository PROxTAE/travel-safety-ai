"""Following an assessment run: poll, cancel, stream.

Three routes, and the same rule under all of them: ownership is a repository query, and a run
belonging to somebody else is reported as 404 exactly like one that does not exist. Run ids are
UUIDs, but a 403 would still confirm which ones are real.

**Caching.** A run's state belongs to one person's journey, so nothing here may be stored by a
shared cache. The poll endpoint sends `private` with a very small max-age — the point of polling is
freshness, and a proxy holding a run's state for even a few seconds can show a traveller a verdict
that has since changed. The SSE stream is `no-store` outright, along with `X-Accel-Buffering: no`,
because a buffering proxy turns a progress stream into one long silence followed by everything at
once.

**Stream limits.** One stream has a hard duration cap and a per-user concurrency cap. A client that
needs longer reconnects with `Last-Event-ID`, which costs it nothing and stops an abandoned tab
holding a worker open indefinitely.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request, Response
from fastapi.responses import StreamingResponse

from app.api.responses import data_response
from app.api.v1.me import TravelPrincipal
from app.auth.dependencies import DbSession
from app.clients.agent import AgentClient
from app.clients.recommendation import RecommendationClient
from app.db.engine import session_scope
from app.domain import run as machine
from app.errors.exceptions import Conflict, NotFound
from app.observability.logging import get_logger
from app.observability.metrics import active_sse_connections
from app.repositories import requests as requests_repo
from app.schemas.envelope import DataResponse
from app.schemas.run import TERMINAL_EVENTS, RunStateModel
from app.security.rate_limit import rate_limit
from app.services import run_events
from app.services import runs as orchestrator

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/runs",
    tags=["assessments"],
    dependencies=[Depends(rate_limit("runs"))],
)


RequestIdPath = Annotated[uuid.UUID, Path(description="The run to follow.")]


@router.get(
    "/{request_id}",
    response_model=DataResponse[RunStateModel],
    summary="Poll an assessment run",
)
async def get_run(
    request: Request,
    response: Response,
    request_id: RequestIdPath,
    session: DbSession,
    principal: TravelPrincipal,
) -> DataResponse[RunStateModel]:
    """Current state of a run, refreshed from the agent when it is still in flight.

    The fallback for clients that cannot hold an SSE connection open — and the source of truth
    when they can, because the stream reports progress while this reports the record.
    """
    row = await requests_repo.get_owned(session, owner_id=principal.user_id, request_id=request_id)
    if row is None:
        raise NotFound("run")

    settings = request.app.state.settings

    if not machine.is_terminal(row.status):
        row = await orchestrator.reconcile(
            session,
            request.app.state.redis,
            settings,
            row=row,
            agent=AgentClient(request.app.state.internal_http, settings),
            recommendations=RecommendationClient(request.app.state.internal_http, settings),
            correlation_id=str(getattr(request.state, "correlation_id", "")) or None,
        )

    _private_cache(response, settings.run_status_cache_seconds)
    return data_response(request, orchestrator.to_state(row))


@router.delete(
    "/{request_id}",
    response_model=DataResponse[RunStateModel],
    summary="Cancel an assessment run",
)
async def cancel_run(
    request: Request,
    response: Response,
    request_id: RequestIdPath,
    session: DbSession,
    principal: TravelPrincipal,
) -> DataResponse[RunStateModel]:
    """Stop work that is still outstanding.

    409 when the run already reached a terminal state: there is nothing to cancel, and reporting
    success would tell the traveller they stopped something that had in fact already completed.
    """
    row = await requests_repo.get_owned_for_update(
        session, owner_id=principal.user_id, request_id=request_id
    )
    if row is None:
        raise NotFound("run")

    settings = request.app.state.settings
    cancelled = await orchestrator.cancel(
        session,
        request.app.state.redis,
        settings,
        row=row,
        agent=AgentClient(request.app.state.internal_http, settings),
        correlation_id=str(getattr(request.state, "correlation_id", "")) or None,
    )
    if not cancelled:
        raise Conflict("This assessment has already finished, so there was nothing left to cancel.")

    _private_cache(response, 0)
    return data_response(request, orchestrator.to_state(row))


@router.get(
    "/{request_id}/events",
    summary="Follow an assessment run over SSE",
    response_class=StreamingResponse,
)
async def stream_run_events(
    request: Request,
    request_id: RequestIdPath,
    session: DbSession,
    principal: TravelPrincipal,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=64)] = None,
) -> StreamingResponse:
    """Server-sent events for one run.

    Ownership is checked **before** the stream opens, while there is still a status code to answer
    with. Once the response has started, an error can only be an event, and a browser's
    `EventSource` would silently retry it for ever.
    """
    row = await requests_repo.get_owned(session, owner_id=principal.user_id, request_id=request_id)
    if row is None:
        raise NotFound("run")

    resume_from = run_events.validate_last_event_id(last_event_id)

    generator = _events(
        request=request,
        request_id=row.id,
        owner_id=principal.user_id,
        resume_from=resume_from,
        already_terminal=machine.is_terminal(row.status),
    )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            # A run's progress is one person's. Nothing between here and the browser may keep it.
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            # Without this nginx buffers the stream and the traveller sees nothing until the end,
            # which defeats the only reason progress events exist.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Vary": "Authorization",
        },
    )


async def _events(
    *,
    request: Request,
    request_id: uuid.UUID,
    owner_id: uuid.UUID,
    resume_from: str,
    already_terminal: bool,
) -> AsyncIterator[str]:
    """The stream body.

    Runs outside the request's database session: the handler's session closes when the response
    starts, and holding a pooled connection open for the life of a stream would exhaust the pool
    with a handful of clients. Each database read here opens and closes its own short session.
    """
    settings = request.app.state.settings
    redis = request.app.state.redis
    session_factory = request.app.state.session_factory

    counter = run_events.streams_key(settings, owner_id)
    admitted = await _admit(redis, counter, settings.sse_max_streams_per_user)
    if not admitted:
        # Refused politely, as an event, because the response has already begun. A failure the
        # client can read beats a socket that closes for no stated reason.
        yield run_events.format_sse(
            "0-0",
            "run.failed",
            {
                "request_id": str(request_id),
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many open progress streams. Close one and try again.",
                    "field_errors": [],
                    "retryable": True,
                    "retry_after_seconds": 5,
                },
            },
        )
        return

    active_sse_connections.inc()
    started = datetime.now(UTC)
    last_id = resume_from
    block_ms = max(250, int(settings.sse_heartbeat_seconds * 1000))

    try:
        while True:
            if await request.is_disconnected():
                return

            elapsed = (datetime.now(UTC) - started).total_seconds()
            if elapsed >= settings.sse_max_duration_seconds:
                # The cap is not a failure. The client reconnects with Last-Event-ID and resumes
                # exactly where this left off, so nothing is lost by ending here.
                return

            entries = await run_events.read_after(
                redis,
                settings,
                request_id=request_id,
                last_id=last_id,
                block_ms=block_ms,
            )

            if not entries:
                yield run_events.format_sse(
                    last_id,
                    "heartbeat",
                    {"server_time": datetime.now(UTC).isoformat().replace("+00:00", "Z")},
                )
                # Nothing is being published. If the run finished before this stream opened — or
                # while Redis was unavailable — the record still knows, and the stream must end
                # rather than heartbeat for ever.
                if already_terminal or await _is_finished(session_factory, owner_id, request_id):
                    return
                continue

            for stream_id, fields in entries:
                last_id = stream_id
                decoded = run_events.decode(fields)
                if decoded is None:
                    # Dropped by the contract check. Advancing `last_id` past it is deliberate:
                    # replaying an event that failed validation would fail it again for ever.
                    continue
                event_type, payload = decoded
                yield run_events.format_sse(stream_id, event_type, payload)
                if event_type in TERMINAL_EVENTS:
                    return
    finally:
        active_sse_connections.dec()
        with contextlib.suppress(Exception):
            await redis.decr(counter)


async def _admit(redis: object, counter: str, limit: int) -> bool:
    """Take a slot under the per-user stream cap.

    Fails open when Redis is unavailable. The cap protects against one client holding many
    connections; refusing every stream because the counter is unreachable would turn a Redis blip
    into a total loss of progress reporting, which is the larger harm.
    """
    try:
        current = await redis.incr(counter)  # type: ignore[attr-defined]
        await redis.expire(counter, 3600)  # type: ignore[attr-defined]
    except Exception:
        logger.warning(
            "sse_cap_unavailable",
            event_type="sse",
            detail="stream admitted without counting; Redis unreachable",
        )
        return True

    if int(current) > limit:
        with contextlib.suppress(Exception):
            await redis.decr(counter)  # type: ignore[attr-defined]
        return False
    return True


async def _is_finished(session_factory: object, owner_id: uuid.UUID, request_id: uuid.UUID) -> bool:
    """Whether the run has reached a terminal state, read in its own short session."""
    try:
        async with session_scope(session_factory) as session:  # type: ignore[arg-type]
            row = await requests_repo.get_owned(session, owner_id=owner_id, request_id=request_id)
    except Exception:
        logger.warning("sse_state_check_failed", event_type="sse", request_id=str(request_id))
        return False

    return row is None or machine.is_terminal(row.status)


def _private_cache(response: Response, seconds: int) -> None:
    """Never a shared cache, and never across users.

    `private` keeps the response out of every proxy between here and the browser; `Vary:
    Authorization` stops one user's cached run being served to another on a client that keys by URL
    alone. Zero seconds means `no-store`, which is what a just-cancelled run needs.
    """
    response.headers["Cache-Control"] = f"private, max-age={seconds}" if seconds > 0 else "no-store"
    response.headers["Vary"] = "Authorization"
