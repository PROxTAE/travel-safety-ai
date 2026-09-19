"""SQLAlchemy models for the `provider` schema.

Table and column names follow 00_API_AND_DATA_CONTRACTS.md § 8. Module 04 owns
this schema and must not read or write any other.

Note the retention rule from the same section: raw provider bodies are not
stored. `fetch_log` keeps a query hash and a content hash - enough to audit
which evidence backed a decision, without re-storing licensed content.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "provider"

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Provider(Base):
    """Registry rows mirrored from providers.yaml at startup.

    The YAML stays the source of truth; this table exists so that a fetch_log
    row can reference a provider and so operators can query the active set
    without reading a file inside a container.
    """

    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coverage_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    license_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_version: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class FetchLog(Base):
    __tablename__ = "fetch_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_id: Mapped[str] = mapped_column(
        String(64), ForeignKey(f"{SCHEMA}.providers.id", ondelete="CASCADE"), nullable=False
    )
    query_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quality_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )

    __table_args__ = (
        Index("ix_fetch_log_provider_fetched_at", "provider_id", "fetched_at"),
        # Retention sweeps delete by age, so the bare timestamp needs its own index.
        Index("ix_fetch_log_fetched_at", "fetched_at"),
    )


class ProviderHealth(Base):
    __tablename__ = "health"

    provider_id: Mapped[str] = mapped_column(
        String(64), ForeignKey(f"{SCHEMA}.providers.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
