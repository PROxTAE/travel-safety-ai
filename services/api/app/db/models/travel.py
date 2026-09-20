"""The `travel` schema.

`trips` holds the journey a person saved. Origin and destination are JSONB rather than columns
because they are a contract entity (`LocationRef`) that module 04 produces and this service stores
whole: splitting it into eight columns would mean a migration here every time that entity gains a
field, and would lose the provenance of which provider resolved the place.

`revision` is the concurrency token. It is not a timestamp: two writes inside the same millisecond
are indistinguishable by clock, and the failure that guards against — a second browser tab
overwriting a change it never saw — is exactly the case where two writes arrive together.

`idempotency_keys` makes a retried create safe. The key is stored as a digest together with a
digest of the request body: the same key with the same body returns the original trip, the same key
with a different body is a client bug worth reporting rather than a second trip to be created.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

# this codebase is clearer than shouting at every column definition.
from sqlalchemy.dialects.postgresql import UUID as PostgresUuid  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import IDENTITY_SCHEMA, TRAVEL_SCHEMA, Base


class Trip(Base):
    """One saved journey, owned by exactly one person."""

    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint(
            "return_time IS NULL OR return_time > departure_time",
            name="return_after_departure",
        ),
        CheckConstraint("jsonb_array_length(travel_modes) BETWEEN 1 AND 7", name="modes_bounded"),
        # The list query: one user's trips, newest departure first, soft-deleted ones excluded.
        # The partial predicate keeps deleted rows out of the index entirely rather than out of the
        # result set after a scan.
        Index(
            "ix_trips_owner_departure",
            "user_id",
            text("departure_time DESC"),
            text("id DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Feeds the retention purge, which looks only at rows already soft-deleted.
        Index(
            "ix_trips_deleted_at",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
        {"schema": TRAVEL_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True),
        ForeignKey(f"{IDENTITY_SCHEMA}.user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        comment="Owner. Every query in the repository filters on it.",
    )

    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        comment="Optimistic concurrency token, served as the ETag. Incremented by every mutation.",
    )

    title: Mapped[str | None] = mapped_column(String(256), nullable=True)

    origin: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="LocationRef as the contract defines it, stored whole with its provider.",
    )
    destination: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    departure_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    return_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment=(
            "IANA zone the traveller planned in. Kept beside the UTC instants because "
            "'09:30 local' survives a daylight-saving change and an offset does not."
        ),
    )

    travel_modes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    selected_route_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True),
        nullable=True,
        comment="Set only by apply-route, after the server has checked the route is not closed.",
    )
    previous_selected_route_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True), nullable=True
    )
    latest_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True),
        nullable=True,
        comment="Most recent assessment started for this trip. Cleared when the journey changes.",
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'DRAFT'")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft delete; the purge of child data runs asynchronously under retention.",
    )

    def __repr__(self) -> str:
        # No origin, no destination, no title: a repr ends up in tracebacks, and all three say
        # where somebody is going.
        return f"Trip(id={self.id!r}, revision={self.revision!r}, status={self.status!r})"


class IdempotencyKey(Base):
    """One recorded outcome for one client-supplied key.

    Scoped to the user, so two people using the same key — which a client library generating short
    keys makes likely — cannot see each other's result.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "key_digest", name="uq_idempotency_user_key"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
        {"schema": TRAVEL_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True),
        ForeignKey(f"{IDENTITY_SCHEMA}.user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    key_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 of the client's key. The key itself is never stored.",
    )
    request_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment=(
            "SHA-256 of the canonical request body, so the same key with a different payload is "
            "detected as a conflict rather than answered with the wrong resource."
        ),
    )

    operation: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Which endpoint claimed the key."
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(PostgresUuid(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="After this the key may be reused; the retention job removes the row.",
    )

    def __repr__(self) -> str:
        return f"IdempotencyKey(operation={self.operation!r}, resource_id={self.resource_id!r})"
