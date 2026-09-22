"""PostgreSQL-backed persistence for the agent: the LangGraph checkpointer plus this service's own
`agent.runs` bookkeeping (00_API_AND_DATA_CONTRACTS.md §8, "agent — คน 3").

LangGraph's `AsyncPostgresSaver` owns and migrates its own tables via `.setup()`; `agent.runs` (and
the not-yet-written-to `agent.tool_calls`) are plain hand-rolled SQL files in
`services/agent/migrations/`, applied the same way
`services/decision-engine/app/repositories/migrations.py` does: tracked in an
`agent.schema_migrations` table, one transaction per file, applied once.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.checkpoints.serde import agent_checkpoint_serde
from app.graph.state import AgentState, RunStatus
from app.settings import Settings

MIGRATIONS_PATH = Path(__file__).resolve().parents[2] / "migrations"


async def apply_migrations(conn_string: str, migrations_path: Path = MIGRATIONS_PATH) -> None:
    """Apply local SQL migrations once, in lexical order, inside one transaction each."""
    async with await psycopg.AsyncConnection.connect(conn_string, autocommit=True) as connection:
        await connection.execute("CREATE SCHEMA IF NOT EXISTS agent")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent.schema_migrations (
                migration_name text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cursor = await connection.execute("SELECT migration_name FROM agent.schema_migrations")
        applied = {row[0] for row in await cursor.fetchall()}
        migration_files = await asyncio.to_thread(lambda: sorted(migrations_path.glob("*.sql")))
        for migration_file in migration_files:
            if migration_file.name in applied:
                continue
            sql = await asyncio.to_thread(migration_file.read_text, encoding="utf-8")
            async with connection.transaction():
                await connection.execute(sql)
                await connection.execute(
                    "INSERT INTO agent.schema_migrations (migration_name) VALUES (%s)",
                    (migration_file.name,),
                )


@asynccontextmanager
async def agent_checkpointer(conn_string: str) -> AsyncIterator[AsyncPostgresSaver]:
    """Open the LangGraph checkpointer and ensure its own tables exist.

    Held open for the life of the process, per `AsyncPostgresSaver.from_conn_string`'s own
    contract — callers use this as the app's lifespan context, not per-request.
    """
    async with AsyncPostgresSaver.from_conn_string(
        conn_string, serde=agent_checkpoint_serde()
    ) as saver:
        await saver.setup()
        yield saver


class RunsRepository:
    """Reads and writes `agent.runs` — the run-lifecycle record `GET /internal/v1/runs/{id}` reads,
    independent of LangGraph's own checkpoint history (which the graph itself owns via the
    checkpointer, not through this class).
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create(self, state: AgentState, settings: Settings, thread_id: str) -> None:
        request = state.input.travel_request
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO agent.runs (
                    request_id, trip_id, conversation_id, thread_id, user_scope_hash, status,
                    graph_version, contract_version, budgets_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(state.identity.request_id),
                    str(state.identity.trip_id),
                    str(request.conversation_id) if request.conversation_id else None,
                    thread_id,
                    state.identity.user_scope_hash,
                    state.control.status.value,
                    state.plan.graph_version,
                    state.versions.contract,
                    Jsonb(settings.initial_budget()),
                ),
            )

    async def update_final(self, state: AgentState) -> None:
        request_id = str(state.identity.request_id)
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE agent.runs
                SET status = %s, final_state = %s, updated_at = now()
                WHERE request_id = %s
                """,
                (state.control.status.value, Jsonb(state.model_dump(mode="json")), request_id),
            )

    async def mark_cancelled(self, request_id: UUID) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "UPDATE agent.runs SET status = %s, updated_at = now() WHERE request_id = %s",
                (RunStatus.CANCELLED.value, str(request_id)),
            )

    #: Columns `get()` returns, in select order — kept explicit (no `SELECT *`) so the tuple this
    #: method unpacks always lines up with what it selected, and adding a column to the migration
    #: never silently changes this method's output shape.
    _GET_COLUMNS = (
        "status",
        "graph_version",
        "thread_id",
        "user_scope_hash",
        "final_state",
    )

    async def get(self, request_id: UUID) -> dict[str, object] | None:
        columns = ", ".join(self._GET_COLUMNS)
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                f"SELECT {columns} FROM agent.runs WHERE request_id = %s",  # noqa: S608
                (str(request_id),),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(zip(self._GET_COLUMNS, row, strict=True))
