"""Tests for the compiled graph as a whole: shape, checksum, and the three lifecycles Phase 1's
exit criterion asks for — validation, needs-input, and cancel — with no fake recommendation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.checkpoints.serde import agent_checkpoint_serde
from app.graph.builder import GRAPH_VERSION, build_graph, graph_checksum
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


def _location(confirmed: bool = True) -> LocationRef:
    return LocationRef(
        place_id="p1",
        display_name="Bangkok",
        coordinates=GeoPoint(coordinates=(100.5, 13.7)),
        country_code="TH",
        timezone="Asia/Bangkok",
        provider="test",
        confirmed_by_user=confirmed,
    )


def _state(
    *,
    confirmed: bool = True,
    cancelled: bool = False,
    deadline_delta: timedelta = timedelta(seconds=45),
    expired: bool = False,
    question: str | None = None,
) -> AgentState:
    # expired=True: started_at/deadline_at both land in the past (relative to wall-clock now),
    # while still satisfying ControlSection's own deadline_at > started_at invariant — see the
    # matching helper/comment in tests/test_budgets.py.
    now = datetime.now(UTC) - timedelta(minutes=10) if expired else datetime.now(UTC)
    request_id = uuid.uuid4()
    trip_id = uuid.uuid4()
    request = TravelRequest(
        request_id=request_id,
        trip_id=trip_id,
        origin=_location(confirmed),
        destination=_location(confirmed),
        departure_time=now + timedelta(hours=1),
        travel_modes=["TRAIN"],
        question=question,
        locale="th-TH",
        timezone="Asia/Bangkok",
    )
    return AgentState(
        identity=IdentitySection(
            request_id=request_id, correlation_id=uuid.uuid4(), trip_id=trip_id, user_scope_hash="h"
        ),
        input=InputSection(travel_request=request),
        plan=PlanSection(graph_version=GRAPH_VERSION),
        control=ControlSection(
            started_at=now, deadline_at=now + deadline_delta, cancelled=cancelled
        ),
        versions=VersionsSection(contract="1.0.0", graph=GRAPH_VERSION),
    )


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[arg-type]


def test_graph_checksum_is_deterministic() -> None:
    assert graph_checksum() == graph_checksum()
    assert len(graph_checksum()) == 64  # sha256 hex digest


def test_graph_compiles() -> None:
    build_graph(_settings())


class TestLifecycle:
    async def test_confirmed_request_fails_at_the_first_unimplemented_tool_no_fake_result(
        self,
    ) -> None:
        graph = build_graph(_settings(), InMemorySaver(serde=agent_checkpoint_serde()))
        config = RunnableConfig(configurable={"thread_id": str(uuid.uuid4())})

        raw = await graph.ainvoke(_state(confirmed=True), config=config)
        result = AgentState.model_validate(raw)

        assert result.control.status is RunStatus.FAILED
        assert result.control.errors == ["DEPENDENCY_UNAVAILABLE"]
        assert result.result.recommendation_id is None
        # It got past validate_input, classify_intent and check_required_fields (3 steps) before
        # failing on fetch_external_data — proof the earlier real nodes ran.
        assert result.control.step_count in {4, 5}

    async def test_emergency_intent_skips_straight_to_the_shortcut(self) -> None:
        """The shortcut is not implemented yet (see emergency_shortcut.py) — the assertion here
        is about the *path*: it must never touch check_required_fields/fetch_external_data, not
        about the eventual result."""
        graph = build_graph(_settings(), InMemorySaver(serde=agent_checkpoint_serde()))
        config = RunnableConfig(configurable={"thread_id": str(uuid.uuid4())})

        raw = await graph.ainvoke(
            _state(confirmed=False, question="help me, there was an accident"), config=config
        )
        result = AgentState.model_validate(raw)

        assert result.control.status is RunStatus.FAILED
        assert result.control.errors == ["INTERNAL_ERROR"]
        # validate_input(1) + classify_intent(2) + emergency_shortcut(3) — never reached
        # check_required_fields, even though origin/destination are unconfirmed.
        assert result.control.step_count == 3
        assert result.input.missing_fields == []

    async def test_unconfirmed_locations_stop_at_needs_input(self) -> None:
        graph = build_graph(_settings(), InMemorySaver(serde=agent_checkpoint_serde()))
        config = RunnableConfig(configurable={"thread_id": str(uuid.uuid4())})

        raw = await graph.ainvoke(_state(confirmed=False), config=config)
        result = AgentState.model_validate(raw)

        assert result.control.status is RunStatus.NEEDS_INPUT
        assert result.input.missing_fields == [
            "origin.confirmed_by_user",
            "destination.confirmed_by_user",
        ]

    async def test_cancelled_flag_stops_the_run_immediately(self) -> None:
        graph = build_graph(_settings(), InMemorySaver(serde=agent_checkpoint_serde()))
        config = RunnableConfig(configurable={"thread_id": str(uuid.uuid4())})

        raw = await graph.ainvoke(_state(cancelled=True), config=config)
        result = AgentState.model_validate(raw)

        assert result.control.status is RunStatus.CANCELLED
        assert result.control.step_count == 1

    async def test_past_deadline_fails_with_dependency_timeout(self) -> None:
        graph = build_graph(_settings(), InMemorySaver(serde=agent_checkpoint_serde()))
        config = RunnableConfig(configurable={"thread_id": str(uuid.uuid4())})

        raw = await graph.ainvoke(_state(expired=True), config=config)
        result = AgentState.model_validate(raw)

        assert result.control.status is RunStatus.FAILED
        assert result.control.errors == ["DEPENDENCY_TIMEOUT"]

    async def test_never_reaches_completed_in_phase_1(self) -> None:
        """Property check standing in for the Phase 6 "no fake result" evaluation suite: every
        terminal status reachable today is one of the honest ones — never COMPLETED/PARTIAL,
        since nothing can produce a real recommendation_id yet."""
        graph = build_graph(_settings(), InMemorySaver(serde=agent_checkpoint_serde()))
        outcomes = set()
        for confirmed, cancelled in [(True, False), (False, False), (True, True)]:
            config = RunnableConfig(configurable={"thread_id": str(uuid.uuid4())})
            raw = await graph.ainvoke(
                _state(confirmed=confirmed, cancelled=cancelled), config=config
            )
            outcomes.add(AgentState.model_validate(raw).control.status)
        assert outcomes <= {RunStatus.FAILED, RunStatus.NEEDS_INPUT, RunStatus.CANCELLED}
        assert RunStatus.COMPLETED not in outcomes
        assert RunStatus.PARTIAL not in outcomes
