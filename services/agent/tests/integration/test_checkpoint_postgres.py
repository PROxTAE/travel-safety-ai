"""Integration tests for app/checkpoints/postgres.py against a real PostgreSQL (Testcontainers, or
TEST_DATABASE_URL inside compose — see tests/integration/database.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from psycopg_pool import AsyncConnectionPool

from app.checkpoints.postgres import RunsRepository, agent_checkpointer, apply_migrations
from app.graph.builder import build_graph
from app.graph.state import (
    AgentState,
    ControlSection,
    GeoPoint,
    IdentitySection,
    InputSection,
    LocationRef,
    PlanSection,
    RunStatus,
    TravelRequest,
    VersionsSection,
)
from app.settings import Settings
from tests.integration.database import provision_database, requires_database


def _location() -> LocationRef:
    return LocationRef(
        place_id="p1",
        display_name="Bangkok",
        coordinates=GeoPoint(coordinates=(100.5, 13.7)),
        country_code="TH",
        timezone="Asia/Bangkok",
        provider="test",
        confirmed_by_user=True,
    )


def _state() -> AgentState:
    now = datetime.now(UTC)
    request_id = uuid.uuid4()
    trip_id = uuid.uuid4()
    request = TravelRequest(
        request_id=request_id,
        trip_id=trip_id,
        origin=_location(),
        destination=_location(),
        departure_time=now + timedelta(hours=1),
        travel_modes=["TRAIN"],
        locale="th-TH",
        timezone="Asia/Bangkok",
    )
    return AgentState(
        identity=IdentitySection(
            request_id=request_id, correlation_id=uuid.uuid4(), trip_id=trip_id, user_scope_hash="h"
        ),
        input=InputSection(travel_request=request),
        plan=PlanSection(graph_version="0.1.0"),
        control=ControlSection(started_at=now, deadline_at=now + timedelta(seconds=45)),
        versions=VersionsSection(contract="1.0.0", graph="0.1.0"),
    )


@requires_database
@pytest.mark.integration
async def test_migrations_apply_once_and_are_safe_to_repeat() -> None:
    with provision_database() as conn_string:
        await apply_migrations(conn_string)
        await apply_migrations(conn_string)  # must not fail, must not reapply


@requires_database
@pytest.mark.integration
async def test_runs_repository_round_trip() -> None:
    with provision_database() as conn_string:
        await apply_migrations(conn_string)
        pool = AsyncConnectionPool(conn_string, min_size=1, max_size=2)
        await pool.open()
        try:
            repo = RunsRepository(pool)
            state = _state()
            await repo.create(
                state, Settings(_env_file=None), thread_id=str(state.identity.request_id)
            )  # type: ignore[arg-type]

            row = await repo.get(state.identity.request_id)
            assert row is not None
            assert row["status"] == RunStatus.QUEUED.value
            assert row["final_state"] is None

            finished = state.model_copy(
                update={"control": state.control.model_copy(update={"status": RunStatus.FAILED})}
            )
            await repo.update_final(finished)

            row = await repo.get(state.identity.request_id)
            assert row is not None
            assert row["status"] == RunStatus.FAILED.value
            assert row["final_state"] is not None

            await repo.mark_cancelled(state.identity.request_id)
            row = await repo.get(state.identity.request_id)
            assert row is not None
            assert row["status"] == RunStatus.CANCELLED.value
        finally:
            await pool.close()


@requires_database
@pytest.mark.integration
async def test_checkpointer_persists_a_real_run() -> None:
    with provision_database() as conn_string:
        async with agent_checkpointer(conn_string) as saver:
            graph = build_graph(Settings(_env_file=None), saver)  # type: ignore[arg-type]
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}

            raw = await graph.ainvoke(_state(), config=config)
            result = AgentState.model_validate(raw)
            # fetch_external_data is not implemented yet (Phase 3/4) — this proves the run's
            # progress through validate_input/classify_intent/check_required_fields was really
            # persisted to PostgreSQL and read back, not that the run completed.
            assert result.control.status is RunStatus.FAILED

            snapshot = await graph.aget_state(config)
            restored = AgentState.model_validate(snapshot.values)
            assert restored.control.status is RunStatus.FAILED
            assert restored.identity.request_id == result.identity.request_id
