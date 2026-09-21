"""Async unit of work for integration schema."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def build_engine(url: str):
    return create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def build_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def unit_of_work(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        async with session.begin():
            yield session
