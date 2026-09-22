"""Tests for app/budgets — the stop-condition guard that guarantees no unlimited loop."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.budgets import (
    BUDGET_EXCEEDED_ERROR_CODE,
    NodeNotImplementedError,
    check_stop_conditions,
    guard_node,
)
from app.graph.state import (
    AgentState,
    ControlSection,
    GeoPoint,
    IdentitySection,
    InputSection,
    LocationRef,
    PlanSection,
    RunStatus,
    TravelPreferences,
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
    step_count: int = 0,
    tool_call_count: int = 0,
    cancelled: bool = False,
    deadline_delta: timedelta = timedelta(seconds=45),
    expired: bool = False,
) -> AgentState:
    """`expired=True` puts both `started_at` and `deadline_at` safely in the past (10 minutes ago
    plus `deadline_delta`) so the deadline has already passed *and* `ControlSection`'s own
    `deadline_at > started_at` invariant still holds — a deadline in the past relative to
    `started_at` itself is not a valid state, only one in the past relative to wall-clock `now`.
    """
    now = datetime.now(UTC) - timedelta(minutes=10) if expired else datetime.now(UTC)
    request_id = uuid.uuid4()
    trip_id = uuid.uuid4()
    request = TravelRequest(
        request_id=request_id,
        trip_id=trip_id,
        origin=_location(),
        destination=_location(),
        departure_time=now + timedelta(hours=1),
        travel_modes=["TRAIN"],
        preferences=TravelPreferences(),
        locale="th-TH",
        timezone="Asia/Bangkok",
    )
    return AgentState(
        identity=IdentitySection(
            request_id=request_id,
            correlation_id=uuid.uuid4(),
            trip_id=trip_id,
            user_scope_hash="hash",
        ),
        input=InputSection(travel_request=request),
        plan=PlanSection(graph_version="0.1.0"),
        control=ControlSection(
            started_at=now,
            deadline_at=now + deadline_delta,
            cancelled=cancelled,
            step_count=step_count,
            tool_call_count=tool_call_count,
        ),
        versions=VersionsSection(contract="1.0.0", graph="0.1.0"),
    )


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_no_stop_condition_for_a_fresh_run() -> None:
    assert check_stop_conditions(_state(), _settings()) is None


def test_cancelled_wins_over_everything_else() -> None:
    stop = check_stop_conditions(
        _state(cancelled=True, step_count=9999, expired=True),
        _settings(),
    )
    assert stop is not None
    assert stop.status is RunStatus.CANCELLED
    assert stop.error_code is None


def test_past_deadline_is_failed_with_dependency_timeout() -> None:
    stop = check_stop_conditions(_state(expired=True), _settings())
    assert stop is not None
    assert stop.status is RunStatus.FAILED
    assert stop.error_code == "DEPENDENCY_TIMEOUT"


def test_deadline_beats_budget_when_both_are_exceeded() -> None:
    stop = check_stop_conditions(_state(step_count=999, expired=True), _settings())
    assert stop is not None
    assert stop.error_code == "DEPENDENCY_TIMEOUT"


def test_step_budget_exceeded() -> None:
    settings = _settings(max_agent_steps=3)
    stop = check_stop_conditions(_state(step_count=3), settings)
    assert stop is not None
    assert stop.status is RunStatus.FAILED
    assert stop.error_code == BUDGET_EXCEEDED_ERROR_CODE


def test_tool_call_budget_exceeded() -> None:
    settings = _settings(max_tool_calls=5)
    stop = check_stop_conditions(_state(tool_call_count=5), settings)
    assert stop is not None
    assert stop.error_code == BUDGET_EXCEEDED_ERROR_CODE


def test_one_step_under_budget_is_fine() -> None:
    settings = _settings(max_agent_steps=3)
    assert check_stop_conditions(_state(step_count=2), settings) is None


class TestGuardNode:
    async def test_increments_step_count_before_running_the_node(self) -> None:
        async def probe(state: AgentState) -> dict[str, object]:
            assert state.control.step_count == 1
            return {}

        guarded = guard_node("probe", probe, _settings())
        result = await guarded(_state(step_count=0))
        assert result["control"].step_count == 1  # type: ignore[union-attr]

    async def test_stops_before_running_the_node_when_over_budget(self) -> None:
        calls = []

        async def probe(state: AgentState) -> dict[str, object]:
            calls.append(state)
            return {}

        guarded = guard_node("probe", probe, _settings(max_agent_steps=1))
        result = await guarded(_state(step_count=1))
        assert calls == []
        assert result["control"].status is RunStatus.FAILED  # type: ignore[union-attr]
        assert result["control"].errors == [BUDGET_EXCEEDED_ERROR_CODE]  # type: ignore[union-attr]

    async def test_node_not_implemented_becomes_failed_internal_error(self) -> None:
        async def not_done(state: AgentState) -> dict[str, object]:
            raise NodeNotImplementedError("not built yet")

        guarded = guard_node("not_done", not_done, _settings())
        result = await guarded(_state())
        assert result["control"].status is RunStatus.FAILED  # type: ignore[union-attr]
        assert result["control"].errors == ["INTERNAL_ERROR"]  # type: ignore[union-attr]

    async def test_node_control_patch_is_layered_onto_the_incremented_control(self) -> None:
        async def sets_needs_input(state: AgentState) -> dict[str, object]:
            return {"control_patch": {"status": RunStatus.NEEDS_INPUT}}

        guarded = guard_node("sets_needs_input", sets_needs_input, _settings())
        result = await guarded(_state(step_count=0))
        control = result["control"]
        assert control.status is RunStatus.NEEDS_INPUT  # type: ignore[union-attr]
        assert control.step_count == 1  # type: ignore[union-attr]

    async def test_other_fields_pass_through_untouched(self) -> None:
        async def touches_input(state: AgentState) -> dict[str, object]:
            return {"input": state.input.model_copy(update={"missing_fields": ["x"]})}

        guarded = guard_node("touches_input", touches_input, _settings())
        result = await guarded(_state())
        assert result["input"].missing_fields == ["x"]  # type: ignore[union-attr]
        assert "control" in result
