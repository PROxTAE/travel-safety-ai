from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.configuration_error: str | None = None
        self.engine: AsyncEngine | None = None
        self.sessions: async_sessionmaker[AsyncSession] | None = None
        try:
            url = settings.sqlalchemy_url()
        except ValueError as exc:
            self.configuration_error = str(exc)
            return
        self.engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_pool_size,
            connect_args={
                "timeout": settings.dependency_timeout_seconds,
                "command_timeout": settings.dependency_timeout_seconds,
            },
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()

    async def check_ready(self) -> tuple[bool, str | None]:
        if self.engine is None:
            return False, self.configuration_error or "Database is not configured"
        try:
            async with self.engine.connect() as connection:
                result = await connection.execute(
                    text(
                        "SELECT "
                        "to_regclass('knowledge.alembic_version') IS NOT NULL "
                        "AND to_regclass('knowledge.model_versions') IS NOT NULL"
                    )
                )
                if not bool(result.scalar_one()):
                    return False, "Knowledge schema migrations are not at a usable baseline"
            return True, None
        except Exception:
            return False, "Database connection or migration check failed"

    async def session(self) -> AsyncIterator[AsyncSession]:
        if self.sessions is None:
            raise RuntimeError(self.configuration_error or "Database is unavailable")
        async with self.sessions() as session:
            yield session
