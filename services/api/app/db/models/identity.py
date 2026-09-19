"""The `identity` schema.

Phase 2 needs exactly one table: the mapping from an OIDC subject to an internal user id. Consent
records and the emergency profile are phase 3 and are not declared here — an empty table that looks
implemented is worse than one that does not exist yet.

Two rules from §"User identity" of the module plan are enforced by the shape of this table. The
Keycloak `sub` is an external identity and gets its own column; the primary key is an internal
UUID. And e-mail is nowhere near it: an address changes, is reused, and is personal data, so it is
never a key and is never stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func, text

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
        doc="The OIDC `sub`. Opaque and stable for the lifetime of the identity provider account.",
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
        doc=(
            "Set to refuse a user who still holds a valid token. A JWT cannot be revoked, so "
            "without a local check a disabled account keeps working until its token expires."
        ),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Soft delete. The purge of owned data runs asynchronously under the retention policy.",
    )

    def __repr__(self) -> str:
        # No subject_id, no locale, nothing that identifies a person: reprs end up in tracebacks.
        return f"UserProfile(id={self.id!r})"
