"""Property test: the graph terminates within budget for every generated state.

`03_TRAVEL_AI_AGENT_IMPLEMENTATION.md` Phase 6 step 5 asks for exactly this: "assert no loops:
property test ว่า graph จบภายใน max steps ทุก generated state". The most meaningful version of that
claim is not "the *current* compiled graph terminates" — every one of its unimplemented nodes
raises on the first call, so it terminates almost trivially today. The claim that matters, and the
one that keeps holding as Phase 3/4/5 fill those nodes in with real logic, is that `guard_node`
(`app/budgets/__init__.py`) itself makes unbounded looping impossible: no matter what a node
returns, wrapping it in `guard_node` bounds the number of times it can run to
`Settings.max_agent_steps`. That is what this test proves, adversarially — a node built
specifically to never stop on its own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from app.budgets import NodeUpdate, guard_node
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

_TERMINAL_STATUSES = frozenset(
    {
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.COMPLETED,
        RunStatus.PARTIAL,
        RunStatus.NEEDS_INPUT,
    }
)


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


def _state(*, step_count: int) -> AgentState:
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
        control=ControlSection(
            started_at=now,
            # Deadline is real wall-clock time far in the future — this property test is about the
            # step/tool-call budget specifically, not the timeout, which hypothesis cannot usefully
            # fuzz against a live clock.
            deadline_at=now + timedelta(hours=1),
            step_count=step_count,
        ),
        versions=VersionsSection(contract="1.0.0", graph="0.1.0"),
    )


async def _never_stops(state: AgentState) -> NodeUpdate:
    """A node built to always signal "keep going forever" — never sets a terminal status, never
    raises. The one thing standing between this and an infinite loop is guard_node itself."""
    del state
    return {}


@given(
    max_agent_steps=st.integers(min_value=1, max_value=30),
    starting_step_count=st.integers(min_value=0, max_value=60),
)
@hypothesis_settings(deadline=None)
async def test_guard_node_bounds_a_pathological_infinite_loop(
    max_agent_steps: int, starting_step_count: int
) -> None:
    settings = Settings(_env_file=None, max_agent_steps=max_agent_steps)  # type: ignore[call-arg]
    guarded = guard_node("never_stops", _never_stops, settings)

    state = _state(step_count=starting_step_count)
    # Generous safety valve so a real property violation fails the assertion below instead of
    # hanging the test suite — never reached if guard_node actually bounds the loop as claimed.
    for _ in range(max_agent_steps + starting_step_count + 5):
        if state.control.status in _TERMINAL_STATUSES:
            break
        update = await guarded(state)
        state = state.model_copy(update=update)
    else:
        raise AssertionError("guard_node did not terminate the loop within the safety valve")

    assert state.control.status in _TERMINAL_STATUSES
    # It stopped specifically because of the step budget, not by accident.
    if starting_step_count >= max_agent_steps:
        assert state.control.status is RunStatus.FAILED
        assert state.control.step_count == starting_step_count + 1
    else:
        assert state.control.status is RunStatus.FAILED
        assert state.control.step_count == max_agent_steps
