"""Run quarantine retention as a separate scheduled container command."""

import asyncio

from app.repositories.db import build_engine, build_session_factory, unit_of_work
from app.repositories.quarantine_repo import QuarantineRepository
from app.settings import get_settings


async def run() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        async with unit_of_work(build_session_factory(engine)) as session:
            await QuarantineRepository(session).purge_before(
                days=settings.quarantine_retention_days
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
