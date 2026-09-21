"""Migration and PostGIS checks on a newly created database."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_fresh_migration_and_spatial_index(isolated_database: str) -> None:
    engine = create_async_engine(isolated_database)
    try:
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT PostGIS_Version()"))).scalar_one()
            names = (
                (
                    await connection.execute(
                        text("""
                SELECT tablename FROM pg_tables WHERE schemaname = 'integration'
            """)
                    )
                )
                .scalars()
                .all()
            )
            assert {"snapshots", "quarantine", "field_lineage", "alembic_version"} <= set(names)
            index = (
                await connection.execute(
                    text("""
                SELECT indexdef FROM pg_indexes
                WHERE schemaname='integration' AND indexname='ix_snapshot_corridor'
            """)
                )
            ).scalar_one()
            assert "gist" in index.lower()
            geography_index = (
                await connection.execute(
                    text("""
                    SELECT indexdef FROM pg_indexes
                    WHERE schemaname='integration' AND indexname='ix_canonical_geography'
                """)
                )
            ).scalar_one()
            assert "gist" in geography_index.lower()
            assert "geography" in geography_index.lower()
            assert (
                await connection.execute(
                    text("""
                SELECT ST_Intersects(
                    ST_Buffer(ST_SetSRID(ST_Point(100.5, 13.7), 4326)::geography, 1000)::geometry,
                    ST_SetSRID(ST_Point(100.5, 13.7), 4326))
            """)
                )
            ).scalar_one() is True
    finally:
        await engine.dispose()
