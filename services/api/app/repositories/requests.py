"""Owner-scoped queries for assessment runs.

Every function takes the owner resolved from the token and filters on it in the query itself,
rather than loading a row and checking afterwards. The difference matters: a check after the fact
is one early `return` away from being skipped, and the row has already been in memory by then.

`advance` is the only way a status changes. It runs the proposed move past `app.domain.run` first,
so a late or replayed message from the agent cannot resurrect a finished run, and it re-reads the
row inside the same transaction so two messages arriving together cannot both win.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.travel import AssessmentRequest
from app.domain import run as machine
from app.observability.logging import get_logger

logger = get_logger(__name__)


async def create(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    trip_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    input_digest: str,
    contract_version: str,
    locale: str,
    timezone: str,
) -> AssessmentRequest:
    """Open a run in QUEUED.

    Flushed, not committed: the caller commits, and it does so before calling the agent. That
    ordering is the reason a run survives an agent that is unreachable.
    """
    row = AssessmentRequest(
        user_id=owner_id,
        trip_id=trip_id,
        conversation_id=conversation_id,
        status="QUEUED",
        input_digest=input_digest,
        contract_version=contract_version,
        locale=locale,
        timezone=timezone,
        missing_fields=[],
        degraded_services=[],
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def get_owned(
    session: AsyncSession, *, owner_id: uuid.UUID, request_id: uuid.UUID
) -> AssessmentRequest | None:
    """One run, or None when it does not exist **or** belongs to somebody else.

    The two cases are deliberately indistinguishable to the caller, so the handler answers 404 to
    both and run ids cannot be probed by watching the status code change.
    """
    row: AssessmentRequest | None = await session.scalar(
        select(AssessmentRequest).where(
            AssessmentRequest.id == request_id,
            AssessmentRequest.user_id == owner_id,
        )
    )
    return row


async def get_owned_for_update(
    session: AsyncSession, *, owner_id: uuid.UUID, request_id: uuid.UUID
) -> AssessmentRequest | None:
    """The same row, locked for the duration of the transaction.

    Used by anything that transitions the state. Two agent messages for one run can arrive at two
    workers at once; without the lock both would read the same status, both would judge their move
    legal, and the later write would win regardless of which event was actually newer.
    """
    row: AssessmentRequest | None = await session.scalar(
        select(AssessmentRequest)
        .where(
            AssessmentRequest.id == request_id,
            AssessmentRequest.user_id == owner_id,
        )
        .with_for_update()
    )
    return row


async def attach_agent_run(
    session: AsyncSession, *, row: AssessmentRequest, agent_run_id: str
) -> None:
    """Record module 03's id for a run this service already committed."""
    row.agent_run_id = agent_run_id
    row.updated_at = datetime.now(UTC)
    await session.flush()


def advance(
    row: AssessmentRequest,
    *,
    status: str,
    stage: str | None = None,
    percent: int | None = None,
    message_key: str | None = None,
    missing_fields: list[str] | None = None,
    recommendation_id: uuid.UUID | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    degraded_services: list[dict[str, Any]] | None = None,
) -> bool:
    """Apply a state change if the machine permits it.

    Returns True when the row moved and False when the move was refused. False is not an error:
    the overwhelmingly common cause is a duplicate or out-of-order message about a run that has
    already finished, and the right response to that is to ignore it quietly.

    Raises `UnknownStatus` for a status outside the contract, because that is version skew between
    two services and deserves to be noticed rather than dropped.
    """
    machine.ensure_known(status)

    if not machine.can_transition(row.status, status):
        logger.info(
            "run_transition_refused",
            event_type="run",
            request_id=str(row.id),
            current=row.status,
            proposed=status,
        )
        return False

    now = datetime.now(UTC)
    row.status = status
    row.updated_at = now

    # A stage the contract does not define is dropped rather than stored: it is a display hint,
    # and an unknown hint is worth less than a clean column.
    if stage is not None:
        row.stage = machine.stage_or_none(stage)
    if percent is not None:
        row.percent = max(0, min(100, percent))
    if message_key is not None:
        row.message_key = message_key
    if missing_fields is not None:
        row.missing_fields = missing_fields
    if recommendation_id is not None:
        row.recommendation_id = recommendation_id
    if error_code is not None:
        row.error_code = error_code
    if error_message is not None:
        row.error_message = error_message
    if degraded_services is not None:
        row.degraded_services = degraded_services

    if machine.is_terminal(status):
        row.completed_at = now
        # A finished run has no outstanding work to describe, and leaving a stale stage behind
        # would let a UI go on showing "Assessing risk" beside a failure.
        row.stage = None
        row.percent = None if status != "COMPLETED" else 100

    return True


async def latest_for_trip(
    session: AsyncSession, *, owner_id: uuid.UUID, trip_id: uuid.UUID
) -> AssessmentRequest | None:
    """The most recent run for one trip, newest first."""
    row: AssessmentRequest | None = await session.scalar(
        select(AssessmentRequest)
        .where(
            AssessmentRequest.user_id == owner_id,
            AssessmentRequest.trip_id == trip_id,
        )
        .order_by(AssessmentRequest.created_at.desc())
        .limit(1)
    )
    return row
