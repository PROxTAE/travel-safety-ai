"""Reading and writing `identity.data_subject_requests`.

Export and deletion are recorded here and carried out by `app.cli.retention`, out of band. Keeping
the request separate from the work is what lets the service say "in progress" honestly: deleting
everything about someone means reaching six other services' schemas through APIs that do not exist
yet, and a status of COMPLETED that only covered `identity` would be a lie told to the one person
entitled to the truth.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import DataSubjectRequest

KIND_EXPORT: Final = "EXPORT"
KIND_DELETE: Final = "DELETE"

STATUS_PENDING: Final = "PENDING"
STATUS_IN_PROGRESS: Final = "IN_PROGRESS"
STATUS_COMPLETED: Final = "COMPLETED"
STATUS_FAILED: Final = "FAILED"

#: Schemas that hold data about a person but belong to other modules. Every deletion run reports
#: these as unreached until those services exist and expose the APIs to reach them.
UNREACHABLE_SCOPES: tuple[str, ...] = (
    "agent",
    "integration",
    "knowledge",
    "decision",
    "recommendation",
)


async def enqueue(session: AsyncSession, *, owner_id: uuid.UUID, kind: str) -> DataSubjectRequest:
    """Record a request, or return the one already in flight.

    Asking twice does not queue the work twice. Someone who clicks delete and then clicks it again
    because nothing visibly happened should not end up with two jobs racing over the same rows.
    """
    existing = await session.scalar(
        select(DataSubjectRequest).where(
            DataSubjectRequest.user_id == owner_id,
            DataSubjectRequest.kind == kind,
            DataSubjectRequest.status.in_([STATUS_PENDING, STATUS_IN_PROGRESS]),
        )
    )
    if existing is not None:
        return existing

    request = DataSubjectRequest(user_id=owner_id, kind=kind, status=STATUS_PENDING)
    session.add(request)
    await session.flush()
    return request


async def get_owned(
    session: AsyncSession, *, owner_id: uuid.UUID, request_id: uuid.UUID
) -> DataSubjectRequest | None:
    """One request, if it belongs to this caller."""
    found: DataSubjectRequest | None = await session.scalar(
        select(DataSubjectRequest).where(
            DataSubjectRequest.id == request_id,
            DataSubjectRequest.user_id == owner_id,
        )
    )
    return found


async def list_owned(session: AsyncSession, *, owner_id: uuid.UUID) -> list[DataSubjectRequest]:
    result = await session.scalars(
        select(DataSubjectRequest)
        .where(DataSubjectRequest.user_id == owner_id)
        .order_by(DataSubjectRequest.requested_at.desc())
    )
    return list(result)


async def claim_next(
    session: AsyncSession, *, kind: str | None = None
) -> DataSubjectRequest | None:
    """Take the oldest pending request, marking it in progress.

    `FOR UPDATE SKIP LOCKED` so two workers never take the same row. There is one worker today, but
    a queue that only works with one is a queue that breaks the first time someone scales it.
    """
    statement = (
        select(DataSubjectRequest)
        .where(DataSubjectRequest.status == STATUS_PENDING)
        .order_by(DataSubjectRequest.requested_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if kind is not None:
        statement = statement.where(DataSubjectRequest.kind == kind)

    request = await session.scalar(statement)
    if request is None:
        return None

    request.status = STATUS_IN_PROGRESS
    request.started_at = datetime.now(UTC)
    await session.flush()
    return request


async def finish(
    session: AsyncSession,
    request: DataSubjectRequest,
    *,
    status: str,
    incomplete_scopes: list[str] | None = None,
    error_code: str | None = None,
) -> DataSubjectRequest:
    """Close a request out, recording honestly what was and was not reached."""
    request.status = status
    request.completed_at = datetime.now(UTC)
    request.incomplete_scopes = incomplete_scopes or []
    request.error_code = error_code
    await session.flush()
    return request
