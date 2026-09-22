"""Contract tests for progress events (app/progress/events.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.progress.events import (
    AGENT_EVENT_ADAPTER,
    EventType,
    HeartbeatEvent,
    RunCompletedEvent,
    RunDegradedEvent,
    RunFailedEvent,
    RunNeedsInputEvent,
    RunProgressEvent,
)

NOW = datetime(2026, 9, 20, 9, 30, tzinfo=UTC)


def _envelope(event_type: str, payload: dict, event_id: int = 1) -> dict:
    return {
        "event_id": event_id,
        "request_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": NOW.isoformat(),
        "event_type": event_type,
        "payload": payload,
    }


def _progress_payload(**overrides: object) -> dict:
    payload: dict = {
        "stage": "FETCHING_EXTERNAL_DATA",
        "status": "STARTED",
        "percent": 20,
        "message_key": "stage.fetching_external_data",
        "started_at": NOW.isoformat(),
    }
    payload.update(overrides)
    return payload


def test_every_contract_event_type_parses_to_its_own_class() -> None:
    cases = {
        "run.accepted": (
            {
                "request_id": str(uuid.uuid4()),
                "status": "QUEUED",
                "submitted_at": NOW.isoformat(),
            },
            None,
        ),
        "run.progress": (_progress_payload(), RunProgressEvent),
        "run.needs_input": (
            {
                "missing_fields": ["departure_time"],
                "prompt_key": "input.departure_time",
            },
            RunNeedsInputEvent,
        ),
        "run.degraded": (
            {
                "service": "external-data",
                "reason": "DEPENDENCY_TIMEOUT",
                "retrying": True,
            },
            RunDegradedEvent,
        ),
        "run.completed": (
            {
                "status": "COMPLETED",
                "recommendation_id": str(uuid.uuid4()),
                "result_url": "/api/v1/runs/abc/result",
            },
            RunCompletedEvent,
        ),
        "run.failed": (
            {
                "error_code": "INTERNAL_ERROR",
                "message_key": "error.internal",
                "retryable": False,
            },
            RunFailedEvent,
        ),
        "heartbeat": ({"server_time": NOW.isoformat()}, HeartbeatEvent),
    }
    assert set(cases) == {e.value for e in EventType}
    for event_type, (payload, expected_cls) in cases.items():
        event = AGENT_EVENT_ADAPTER.validate_python(_envelope(event_type, payload))
        assert event.event_type == event_type
        if expected_cls is not None:
            assert isinstance(event, expected_cls)


def test_event_round_trips_through_json() -> None:
    event = AGENT_EVENT_ADAPTER.validate_python(
        _envelope("run.progress", _progress_payload(), event_id=7)
    )
    restored = AGENT_EVENT_ADAPTER.validate_json(event.model_dump_json())
    assert restored == event
    assert restored.event_id == 7


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(_envelope("run.thinking", {}))


def test_unknown_stage_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(
            _envelope("run.progress", _progress_payload(stage="THINKING"))
        )


@pytest.mark.parametrize(
    "forbidden_field",
    ["chain_of_thought", "prompt", "raw_body", "access_token", "coordinates"],
)
def test_sensitive_fields_cannot_be_added_to_progress_payload(
    forbidden_field: str,
) -> None:
    payload = _progress_payload(**{forbidden_field: "leak"})
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(_envelope("run.progress", payload))


@pytest.mark.parametrize("message_key", ["Checking weather now", "", "Stage.Fetching", "1abc"])
def test_message_key_must_be_a_key_not_free_text(message_key: str) -> None:
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(
            _envelope("run.progress", _progress_payload(message_key=message_key))
        )


@pytest.mark.parametrize("event_id", [0, -1])
def test_event_id_must_be_positive(event_id: int) -> None:
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(
            _envelope("run.progress", _progress_payload(), event_id=event_id)
        )


@pytest.mark.parametrize("percent", [-1, 101])
def test_percent_must_be_between_0_and_100(percent: int) -> None:
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(
            _envelope("run.progress", _progress_payload(percent=percent))
        )


def test_percent_may_be_null() -> None:
    event = AGENT_EVENT_ADAPTER.validate_python(
        _envelope("run.progress", _progress_payload(percent=None))
    )
    assert event.payload.percent is None


def test_started_stage_cannot_have_completed_time() -> None:
    payload = _progress_payload(completed_at=(NOW + timedelta(seconds=1)).isoformat())
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(_envelope("run.progress", payload))


def test_finished_stage_requires_completed_time() -> None:
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(
            _envelope("run.progress", _progress_payload(status="COMPLETED"))
        )


def test_completed_time_cannot_precede_start() -> None:
    payload = _progress_payload(
        status="COMPLETED", completed_at=(NOW - timedelta(seconds=1)).isoformat()
    )
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(_envelope("run.progress", payload))


def test_failed_stage_requires_error_code() -> None:
    payload = _progress_payload(status="FAILED", completed_at=NOW.isoformat())
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(_envelope("run.progress", payload))


def test_needs_input_requires_at_least_one_missing_field() -> None:
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(
            _envelope("run.needs_input", {"missing_fields": [], "prompt_key": "input.missing"})
        )


def test_completed_event_only_allows_completed_or_partial() -> None:
    payload = {
        "status": "FAILED",
        "recommendation_id": str(uuid.uuid4()),
        "result_url": "/api/v1/runs/abc/result",
    }
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(_envelope("run.completed", payload))


def test_naive_datetime_is_rejected() -> None:
    envelope = _envelope("heartbeat", {"server_time": "2026-09-20T09:30:00"})
    with pytest.raises(ValidationError):
        AGENT_EVENT_ADAPTER.validate_python(envelope)
