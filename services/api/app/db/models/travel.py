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

    selected_route_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment=(
            "RouteCandidate.route_id of the applied route. A string, not a UUID: a routing "
            "provider mints these reproducibly (openrouteservice:3ca4459b8d41b503) so the same "
            "question yields the same route. Set only by apply-route, after the server has "
            "checked the route is not closed."
        ),
    )
    previous_selected_route_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    latest_request_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True),
        nullable=True,
        comment="Most recent assessment started for this trip. Cleared when the journey changes.",
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'DRAFT'"))

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


class AssessmentRequest(Base):
    """One assessment run, from the moment it is accepted to the moment it ends.

    This row is the reason a run is never lost. It is committed **before** the agent is called, so
    a crash, a timeout or an agent that is simply down leaves a record the client can still poll
    and the operator can still find. The alternative — call first, write afterwards — loses the
    request entirely in exactly the situation where the traveller most needs to know what happened.

    It is also the authority on status. The agent reports progress, but what this service will
    tell a traveller is what is written here, after `app.domain.run` has decided the report was a
    legal move. A late or replayed message cannot resurrect a finished run.

    What it deliberately does not hold: the question the traveller typed, any prompt, any
    chain-of-thought and any provider payload. `input_digest` is a hash, kept so a retry can be
    recognised, and `agent_run_id` is a foreign reference into module 03's own schema.
    """

    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','NEEDS_INPUT','COMPLETED','PARTIAL',"
            "'FAILED','CANCELLED')",
            name="status_known",
        ),
        CheckConstraint(
            "percent IS NULL OR (percent BETWEEN 0 AND 100)",
            name="percent_bounded",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="completed_after_created",
        ),
        # The poll and the list: one user's runs, newest first. Owner first because every query
        # filters on it.
        Index("ix_requests_owner_created", "user_id", text("created_at DESC")),
        # "What is still in flight", for the operator view and for the stale-run sweep. Partial, so
        # the index holds only the handful of rows that are actually running.
        Index(
            "ix_requests_active",
            "status",
            "created_at",
            postgresql_where=text("status IN ('QUEUED','RUNNING','NEEDS_INPUT')"),
        ),
        Index("ix_requests_trip", "trip_id"),
        {"schema": TRAVEL_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="The request_id the client polls and streams by.",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True),
        ForeignKey(f"{IDENTITY_SCHEMA}.user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        comment="Owner. Every query in the repository filters on it.",
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True),
        ForeignKey(f"{TRAVEL_SCHEMA}.trips.id", ondelete="CASCADE"),
        nullable=True,
        comment="Null for a conversation-only run, which phase 6 adds.",
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'QUEUED'"),
        comment="Advanced only through app.domain.run, which refuses backwards moves.",
    )
    stage: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="Display hint from the agent; dropped if unrecognised."
    )
    percent: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Null whenever the remaining work cannot be estimated honestly.",
    )
    message_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Translation key. Never a rendered sentence, which would be one locale's only.",
    )
    missing_fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    agent_run_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Module 03's id for the same run. Null until the agent has accepted it.",
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True),
        nullable=True,
        comment="Set only after the recommendation has been validated against the contract.",
    )

    error_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="A contract error code, never a downstream message."
    )
    error_message: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Safe, already-sanitised text. No stack, no host, no provider body.",
    )
    degraded_services: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="What was unavailable while this ran, so a thin answer is explainable.",
    )

    input_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment=(
            "SHA-256 of the normalised agent input. Lets a retry be recognised and lets an "
            "operator tell two runs apart without storing what was asked."
        ),
    )
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        # No question, no locale-bearing text: a repr reaches tracebacks and logs.
        return f"AssessmentRequest(id={self.id!r}, status={self.status!r}, stage={self.stage!r})"
