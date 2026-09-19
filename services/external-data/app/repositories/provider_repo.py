"""Persistence for the provider registry mirror, fetch log and health table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import HealthState, ProviderStatus
from app.observability.logging import get_logger
from app.providers.registry import ResolvedRegistry
from app.repositories.db import session_scope
from app.repositories.models import FetchLog, Provider, ProviderHealth

log = get_logger(__name__)


class ProviderRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def sync_registry(self, registry: ResolvedRegistry) -> int:
        """Mirror providers.yaml into the table. Idempotent: safe on every boot.

        `enabled` reflects the *effective* status, so a provider whose credential
        is missing shows as disabled in the database too.
        """
        now = datetime.now(UTC)
        rows = [
            {
                "id": resolved.id,
                "kind": str(resolved.entry.kind),
                "name": resolved.entry.name,
                "enabled": resolved.effective_status is ProviderStatus.ACTIVE,
                "coverage_json": resolved.entry.coverage.model_dump(by_alias=True),
                "license_url": resolved.entry.license.url,
                "config_version": registry.registry.schema_version,
                "updated_at": now,
            }
            for resolved in registry.all()
        ]
        if not rows:
            return 0

        async with session_scope(self._sessions) as session:
            statement = pg_insert(Provider).values(rows)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Provider.id],
                    set_={
                        "kind": statement.excluded.kind,
                        "name": statement.excluded.name,
                        "enabled": statement.excluded.enabled,
                        "coverage_json": statement.excluded.coverage_json,
                        "license_url": statement.excluded.license_url,
                        "config_version": statement.excluded.config_version,
                        "updated_at": statement.excluded.updated_at,
                    },
                )
            )
        return len(rows)

    async def record_fetch(
        self,
        *,
        provider_id: str,
        query_hash: str,
        http_status: int | None,
        fetched_at: datetime,
        expires_at: datetime | None,
        content_hash: str | None,
        quality: dict[str, Any],
    ) -> None:
        async with session_scope(self._sessions) as session:
            session.add(
                FetchLog(
                    id=uuid.uuid4(),
                    provider_id=provider_id,
                    query_hash=query_hash,
                    http_status=http_status,
                    fetched_at=fetched_at,
                    expires_at=expires_at,
                    content_hash=content_hash,
                    quality_json=quality,
                )
            )

    async def prune_fetch_log(self, older_than_days: int) -> int:
        """Retention sweep. Kept as an explicit call rather than a trigger so the
        deletion is reviewable and testable."""
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        async with session_scope(self._sessions) as session:
            result = await session.execute(
                delete(FetchLog).where(FetchLog.fetched_at < cutoff)
            )
        return int(result.rowcount or 0)

    async def upsert_health(
        self,
        *,
        provider_id: str,
        state: HealthState,
        latency_ms: int | None = None,
        quota_remaining: int | None = None,
        reason: str | None = None,
    ) -> None:
        async with session_scope(self._sessions) as session:
            statement = pg_insert(ProviderHealth).values(
                provider_id=provider_id,
                status=str(state),
                latency_ms=latency_ms,
                quota_remaining=quota_remaining,
                checked_at=datetime.now(UTC),
                reason=reason,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ProviderHealth.provider_id],
                    set_={
                        "status": statement.excluded.status,
                        "latency_ms": statement.excluded.latency_ms,
                        "quota_remaining": statement.excluded.quota_remaining,
                        "checked_at": statement.excluded.checked_at,
                        "reason": statement.excluded.reason,
                    },
                )
            )

    async def list_health(self) -> list[ProviderHealth]:
        async with session_scope(self._sessions) as session:
            result = await session.execute(select(ProviderHealth))
            return list(result.scalars().all())
