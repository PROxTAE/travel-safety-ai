from __future__ import annotations

from pathlib import Path

import asyncpg


async def apply_migrations(pool: asyncpg.Pool, migrations_path: Path) -> None:
    """Apply local SQL migrations once, in lexical order, inside one transaction each."""
    migration_files = sorted(migrations_path.glob("*.sql"))
    async with pool.acquire() as connection:
        await connection.execute("CREATE SCHEMA IF NOT EXISTS decision")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS decision.schema_migrations (
                migration_name text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            row["migration_name"]
            for row in await connection.fetch(
                "SELECT migration_name FROM decision.schema_migrations"
            )
        }
        for migration_file in migration_files:
            if migration_file.name in applied:
                continue
            async with connection.transaction():
                await connection.execute(migration_file.read_text(encoding="utf-8"))
                await connection.execute(
                    "INSERT INTO decision.schema_migrations (migration_name) VALUES ($1)",
                    migration_file.name,
                )
