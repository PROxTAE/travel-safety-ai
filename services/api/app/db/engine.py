"""Engine and session lifecycle.

The engine is created once at startup and disposed at shutdown. Creating one per request would
rebuild the connection pool on every call; keeping a module-level global would make the test suite
depend on import order.

Two settings are load-bearing:

* `pool_pre_ping` — PostgreSQL restarts and idle-connection reapers leave dead sockets in the pool.
  Without pre-ping, the first request after a restart fails for no reason the user can understand.
* `statement_timeout` — set server-side on every connection, so a pathological query is cancelled
  by the database rather than holding a pooled connection until the pool is exhausted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.observability.logging import get_logger
from app.settings import Settings

logger = get_logger(__name__)


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine for this process."""
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,  # SQL at INFO would put user data in the logs
        connect_args={
            "timeout": settings.db_connect_timeout_seconds,
            "server_settings": {
                "application_name": f"{settings.service_name}@{settings.app_env}",
                "statement_timeout": str(settings.db_statement_timeout_ms),
            },
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,  # handlers read attributes after commit, while serialising
        autoflush=False,  # flushes happen where the code says so, not as a side effect of a read
    )


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One transaction per unit of work.

    Commit on success, roll back on any exception. A handler that returns normally has its work
    durably written; one that raises leaves nothing half-applied.
    """
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine(engine: AsyncEngine) -> None:
    await engine.dispose()
    logger.info("database_engine_disposed", event_type="lifecycle")
