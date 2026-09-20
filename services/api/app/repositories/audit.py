"""Writing `identity.audit_log`.

One function, and the discipline lives in its signature: `details` takes a dict, and the only
things callers are allowed to put in it are counts, versions and enum values. There is a guard
below that rejects anything else, because "we agreed not to log content" is a rule people forget
and a check is not.

The request and correlation ids come from the context rather than the caller, so an entry can
always be matched to the log lines for the same request.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.identity import AuditLogEntry
from app.middleware.request_context import current_correlation_id, current_request_id

#: What happened. A closed set, so a dashboard can group by it and a reviewer can read the table
#: without guessing what a free-text verb meant.
ACTION_PROFILE_UPDATED: Final = "PROFILE_UPDATED"
ACTION_CONSENT_RECORDED: Final = "CONSENT_RECORDED"
ACTION_EMERGENCY_PROFILE_WRITTEN: Final = "EMERGENCY_PROFILE_WRITTEN"
ACTION_EMERGENCY_PROFILE_READ: Final = "EMERGENCY_PROFILE_READ"
ACTION_EMERGENCY_PROFILE_DELETED: Final = "EMERGENCY_PROFILE_DELETED"
ACTION_TRIP_CREATED: Final = "TRIP_CREATED"
ACTION_TRIP_UPDATED: Final = "TRIP_UPDATED"
ACTION_TRIP_DELETED: Final = "TRIP_DELETED"
ACTION_DATA_EXPORT_REQUESTED: Final = "DATA_EXPORT_REQUESTED"
ACTION_ACCOUNT_DELETION_REQUESTED: Final = "ACCOUNT_DELETION_REQUESTED"
ACTION_ACCOUNT_DELETED: Final = "ACCOUNT_DELETED"
ACTION_DATA_EXPORTED: Final = "DATA_EXPORTED"

#: Keys a caller must never put in `details`, checked because forgetting is easy and the
#: consequence is a second, less guarded copy of the data being audited.
FORBIDDEN_DETAIL_KEYS: frozenset[str] = frozenset(
    {
        "medical_notes",
        "allergies",
        "medications",
        "blood_type",
        "contacts",
        "insurance",
        "payload",
        "plaintext",
        "email",
        "phone",
        "display_name",
        "subject_id",
        "coordinates",
        "latitude",
        "longitude",
        "origin",
        "destination",
        "title",
        "place_id",
    }
)


class AuditDetailRejected(ValueError):
    """`details` carried something that must not be written to the audit log."""


def _check_details(details: dict[str, Any]) -> None:
    offending = sorted(key for key in details if key.lower() in FORBIDDEN_DETAIL_KEYS)
    if offending:
        raise AuditDetailRejected(
            f"audit details must not carry content: {offending}. Record a count or a version."
        )
    for key, value in details.items():
        if isinstance(value, dict | list):
            raise AuditDetailRejected(
                f"audit detail {key!r} is a structure; nested values smuggle content in. "
                "Record a count instead."
            )


async def write(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLogEntry:
    """Record that something happened. Never what it said."""
    payload = details or {}
    _check_details(payload)

    entry = AuditLogEntry(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=current_request_id(),
        correlation_id=current_correlation_id(),
        details=payload,
    )
    session.add(entry)
    await session.flush()
    return entry
