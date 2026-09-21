"""Invalid-input audit and bounded retention."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.metrics import quarantined
from app.repositories.models import Quarantine


class QuarantineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        source_hash: str,
        error_code: str,
        field_path: str | None = None,
        raw_content: dict | None = None,
        raw_storage_permitted: bool = False,
    ) -> Quarantine:
        row = Quarantine(
            source_hash=source_hash,
            error_code=error_code,
            field_path=field_path,
            raw_content=raw_content if raw_storage_permitted else None,
        )
        self.session.add(row)
        await self.session.flush()
        quarantined.labels(error_code=error_code).inc()
        return row

    async def purge_before(self, *, days: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self.session.execute(
            delete(Quarantine).where(Quarantine.created_at < cutoff)
        )
        return result.rowcount or 0
