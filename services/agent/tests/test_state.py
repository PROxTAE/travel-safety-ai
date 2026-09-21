"""Contract tests for AgentState (app/graph/state.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.graph.state import (
    AgentState,
    ControlSection,
    GeoPoint,
    GraphStage,
    LocationRef,
    RunStatus,
    TravelRequest,
)

BANGKOK_TZ = timezone(timedelta(hours=7))


def _location() -> dict:
    return {
        "place_id": "provider-scoped-id",
        "display_name": "Bangkok, Thailand",
        "coordinates": {"type": "Point", "coordinates": [100.5018, 13.7563]},
        "country_code": "TH",
        "timezone": "Asia/Bangkok",
        "provider": "open_meteo",
        "confirmed_by_user": True,
    }


def _travel_request() -> dict:
    return {
        "request_id": str(uuid.uuid4()),
        "trip_id": str(uuid.uuid4()),
        "origin": _location(),
        "destination": _location(),
        "departure_time": datetime(2026, 9, 20, 9, 30, tzinfo=BANGKOK_TZ).isoformat(),
        "travel_modes": ["TRAIN"],
        "locale": "th-TH",
        "timezone": "Asia/Bangkok",
    }


def _agent_state() -> dict:
    request = _travel_request()
    now = datetime.now(UTC)
    return {
        "identity": {
            "request_id": request["request_id"],
            "correlation_id": str(uuid.uuid4()),
            "trip_id": request["trip_id"],
            "user_scope_hash": "hash-only",
        },
        "input": {"travel_request": request},
        "plan": {"graph_version": "0.1.0"},
        "control": {
            "started_at": now.isoformat(),
            "deadline_at": (now + timedelta(seconds=45)).isoformat(),
        },
        "versions": {"contract": "1.0.0", "graph": "0.1.0"},
    }


def test_valid_state_uses_safe_defaults() -> None:
    state = AgentState.model_validate(_agent_state())
    assert state.control.status is RunStatus.QUEUED
    assert state.control.step_count == 0
    assert state.plan.current_stage is None


def test_state_round_trips_through_json_without_loss() -> None:
    state = AgentState.model_validate(_agent_state())
    restored = AgentState.model_validate_json(state.model_dump_json())
    assert restored == state


def test_enum_wire_values_match_contract() -> None:
    assert [s.value for s in RunStatus] == [
        "QUEUED",
        "RUNNING",
        "NEEDS_INPUT",
        "COMPLETED",
        "PARTIAL",
        "FAILED",
        "CANCELLED",
    ]
    assert [s.value for s in GraphStage] == [
        "VALIDATING",
        "FETCHING_EXTERNAL_DATA",
        "INTEGRATING_DATA",
        "ASSESSING_RISK",
        "RETRIEVING_GUIDANCE",
        "EVALUATING_ROUTES",
        "MAKING_DECISION",
        "EXPLAINING",
        "FORMATTING_RESPONSE",
    ]


def test_unknown_field_is_rejected() -> None:
    data = _agent_state()
    data["raw_provider_payload"] = {"anything": "leaks"}
    with pytest.raises(ValidationError):
        AgentState.model_validate(data)


def test_departure_time_without_timezone_is_rejected() -> None:
    data = _travel_request()
    data["departure_time"] = "2026-09-20T09:30:00"
    with pytest.raises(ValidationError):
        TravelRequest.model_validate(data)


def test_return_time_must_be_after_departure() -> None:
    data = _travel_request()
    data["return_time"] = data["departure_time"]
    with pytest.raises(ValidationError):
        TravelRequest.model_validate(data)


def test_travel_modes_must_not_be_empty() -> None:
    data = _travel_request()
    data["travel_modes"] = []
    with pytest.raises(ValidationError):
        TravelRequest.model_validate(data)


def test_question_is_limited_to_2000_characters() -> None:
    data = _travel_request()
    data["question"] = "ก" * 2001
    with pytest.raises(ValidationError):
        TravelRequest.model_validate(data)


@pytest.mark.parametrize(
    "coordinates", [(200.0, 0.0), (-181.0, 0.0), (0.0, 91.0), (0.0, -91.0)]
)
def test_coordinates_out_of_range_are_rejected(
    coordinates: tuple[float, float],
) -> None:
    with pytest.raises(ValidationError):
        GeoPoint(coordinates=coordinates)


@pytest.mark.parametrize("country_code", ["th", "THA", "T", ""])
def test_country_code_must_be_uppercase_alpha2(country_code: str) -> None:
    data = _location()
    data["country_code"] = country_code
    with pytest.raises(ValidationError):
        LocationRef.model_validate(data)


@pytest.mark.parametrize(
    "field", ["step_count", "tool_call_count", "token_usage", "estimated_cost"]
)
def test_budget_counters_cannot_be_negative(field: str) -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        ControlSection(
            started_at=now,
            deadline_at=now + timedelta(seconds=1),
            **{field: -1},
        )


def test_deadline_must_be_after_start() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        ControlSection(started_at=now, deadline_at=now)
