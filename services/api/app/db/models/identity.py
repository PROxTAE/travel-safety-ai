"""The `identity` schema.

Four tables, and the shape of each is a privacy decision as much as a data-modelling one.

`user_profiles` maps an OIDC subject to an internal id. The Keycloak `sub` is an external identity
and gets its own column; the primary key is an internal UUID. E-mail is nowhere near it: an address
changes, is reused, and is personal data, so it is never a key and is never stored.

`consents` is append-only, because the question it has to answer is not "may we do this" but "what
did this person agree to, and when".

`emergency_profiles` holds ciphertext and nothing else — no searchable copy of a blood type or an
allergy. That costs a query nobody needs and removes a whole class of accidental disclosure.

`audit_log` records that something happened, never what it contained. An audit trail that quotes
the data it audits becomes a second, less guarded copy of it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

# this codebase is clearer than shouting at every column definition.
from sqlalchemy.dialects.postgresql import UUID as PostgresUuid  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import IDENTITY_SCHEMA, Base


class UserProfile(Base):
    """One row per person who has signed in at least once."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        # Partial index: the disable check runs on every authenticated request, and only the few
        # disabled rows are worth indexing.
        Index(
            "ix_user_profiles_disabled",
            "disabled_at",
            postgresql_where=text("disabled_at IS NOT NULL"),
        ),
        {"schema": IDENTITY_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    subject_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="OIDC subject; opaque and stable for the life of the provider account.",
    )

    locale: Mapped[str] = mapped_column(String(35), nullable=False, server_default=text("'en-US'"))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'UTC'"))
    home_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set to refuse a caller who still holds a valid, unexpired token.",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft delete; the purge of owned data runs asynchronously under retention.",
    )

    def __repr__(self) -> str:
        # No subject_id, no locale, nothing that identifies a person: reprs end up in tracebacks.
        return f"UserProfile(id={self.id!r})"


class Consent(Base):
    """One versioned consent decision.

    Append-only. Revoking marks the standing record and inserts a new one, so the table answers
    "what did this person agree to, and when" — which is the reason for recording consent at all
    rather than keeping a boolean on the profile.

    `expires_at` is what stops a location grant outliving the errand it was given for. The server
    caps it; a client may ask for less and never for more.
    """

    __tablename__ = "consents"
    __table_args__ = (
        # The hot query is "the standing consents for this user", with the partial predicate doing
        # most of the work.
        Index(
            "ix_consents_user_active",
            "user_id",
            "type",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_consents_user_granted_at", "user_id", "granted_at"),
        {"schema": IDENTITY_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True),
        ForeignKey(f"{IDENTITY_SCHEMA}.user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Version of the consent text the person saw.",
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"Consent(id={self.id!r}, type={self.type!r})"


class EmergencyProfile(Base):
    """Medical and next-of-kin details, sealed.

    Every column is either ciphertext or the metadata needed to open it. There is deliberately no
    searchable copy of anything the person wrote, so a `SELECT *` during debugging shows bytes.

    One row per user, so replacing a profile leaves no older copy behind.
    """

    __tablename__ = "emergency_profiles"
    __table_args__ = ({"schema": IDENTITY_SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True),
        ForeignKey(f"{IDENTITY_SCHEMA}.user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_key: Mapped[bytes] = mapped_column(
        LargeBinary,
        nullable=False,
        comment="Per-record data key, sealed under the key named by key_version.",
    )
    wrapped_key_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Which key-encryption key opens this row.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        # Says nothing about the contents, not even their size.
        return f"EmergencyProfile(user_id={self.user_id!r}, key_version={self.key_version!r})"


class AuditLogEntry(Base):
    """What happened to an account, never what it contained.

    Section 11 of the shared context requires an audit trail; the module plan adds that it must not
    record sensitive content. So this table says a profile was written and under which key version,
    and nothing about allergies, medications or next of kin.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_user_occurred", "user_id", "occurred_at"),
        {"schema": IDENTITY_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True),
        ForeignKey(f"{IDENTITY_SCHEMA}.user_profiles.id", ondelete="SET NULL"),
        nullable=True,
        comment="Nulled when the account is purged; the action still happened.",
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUuid(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUuid(as_uuid=True), nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True), nullable=True
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Counts, versions and enum values only; never a field the person typed.",
    )

    def __repr__(self) -> str:
        return f"AuditLogEntry(action={self.action!r}, occurred_at={self.occurred_at!r})"


class DataSubjectRequest(Base):
    """An export or deletion the person asked for, and how far it has got.

    The work runs out of band: deleting everything about someone means reaching other services'
    schemas through their APIs, and none of those exist yet. Keeping the request and its status
    separate from the work lets a person be told "in progress" honestly rather than "done"
    optimistically.
    """

    __tablename__ = "data_subject_requests"
    __table_args__ = (
        Index(
            "ix_data_subject_requests_pending",
            "status",
            "requested_at",
            postgresql_where=text("status IN ('PENDING', 'IN_PROGRESS')"),
        ),
        {"schema": IDENTITY_SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PostgresUuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUuid(as_uuid=True),
        ForeignKey(f"{IDENTITY_SCHEMA}.user_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'PENDING'")
    )

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    incomplete_scopes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="Schemas this run could not reach; COMPLETED never means erased everywhere.",
    )

    def __repr__(self) -> str:
        return f"DataSubjectRequest(kind={self.kind!r}, status={self.status!r})"
