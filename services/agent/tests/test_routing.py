"""Tests for app/graph/routing — pure branch functions, exercised without a compiled graph."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.graph.routing import (
    after_check_required_fields,
    after_guarded,
    after_validate_final_contract,
    build_after_validate_evidence,
)
from app.graph.state import (
    AgentState,
    ControlSection,
    DataStatus,
    GeoPoint,
    IdentitySection,
    InputSection,
    LocationRef,
    PlanSection,
    QualityFlag,
    QualitySection,
    RunStatus,
    TravelRequest,
    VersionsSection,
)
from app.settings import Settings


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


def _state(
    *,
    status: RunStatus = RunStatus.RUNNING,
    missing_fields: list[str] | None = None,
    quality: QualitySection | None = None,
    evidence_retry_count: int = 0,
) -> AgentState:
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
        input=InputSection(travel_request=request, missing_fields=missing_fields or []),
        plan=PlanSection(graph_version="0.1.0"),
        quality=quality or QualitySection(),
        control=ControlSection(
            started_at=now,
            deadline_at=now + timedelta(seconds=45),
            status=status,
            evidence_retry_count=evidence_retry_count,
        ),
        versions=VersionsSection(contract="1.0.0", graph="0.1.0"),
    )


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_after_guarded_continues_when_running() -> None:
    assert after_guarded(_state(status=RunStatus.RUNNING)) == "continue"


def test_after_guarded_stops_on_cancelled() -> None:
    assert after_guarded(_state(status=RunStatus.CANCELLED)) == "stopped"


def test_after_guarded_stops_on_failed() -> None:
    assert after_guarded(_state(status=RunStatus.FAILED)) == "stopped"


def test_after_guarded_does_not_treat_needs_input_as_stopped() -> None:
    # NEEDS_INPUT is routed by after_check_required_fields, not the generic after_guarded branch.
    assert after_guarded(_state(status=RunStatus.NEEDS_INPUT)) == "continue"


def test_after_check_required_fields_routes_to_needs_input() -> None:
    state = _state(status=RunStatus.NEEDS_INPUT, missing_fields=["origin.confirmed_by_user"])
    assert after_check_required_fields(state) == "needs_input"


def test_after_check_required_fields_continues_when_nothing_missing() -> None:
    assert after_check_required_fields(_state(status=RunStatus.RUNNING)) == "continue"


def test_after_check_required_fields_still_stops_on_a_guard_failure() -> None:
    assert after_check_required_fields(_state(status=RunStatus.FAILED)) == "stopped"


def test_after_validate_final_contract_valid_when_not_failed() -> None:
    assert after_validate_final_contract(_state(status=RunStatus.RUNNING)) == "valid"


def test_after_validate_final_contract_invalid_when_failed() -> None:
    assert after_validate_final_contract(_state(status=RunStatus.FAILED)) == "invalid"


class TestAfterValidateEvidence:
    def test_stops_on_a_guard_failure(self) -> None:
        route = build_after_validate_evidence(_settings())
        assert route(_state(status=RunStatus.FAILED)) == "stopped"

    def test_continues_when_evidence_is_sufficient(self) -> None:
        route = build_after_validate_evidence(_settings())
        state = _state(quality=QualitySection(freshness=DataStatus.FRESH))
        assert route(state) == "continue"

    def test_retries_while_under_the_configured_limit(self) -> None:
        route = build_after_validate_evidence(_settings(evidence_retry_max=1))
        state = _state(quality=QualitySection(freshness=DataStatus.STALE), evidence_retry_count=1)
        assert route(state) == "retry"

    def test_escalates_once_the_limit_is_exceeded(self) -> None:
        route = build_after_validate_evidence(_settings(evidence_retry_max=1))
        state = _state(quality=QualitySection(freshness=DataStatus.STALE), evidence_retry_count=2)
        assert route(state) == "escalate"

    def test_zero_retry_budget_escalates_on_the_first_insufficiency(self) -> None:
        route = build_after_validate_evidence(_settings(evidence_retry_max=0))
        state = _state(
            quality=QualitySection(quality_flags=[QualityFlag.INCOMPLETE]),
            evidence_retry_count=1,
        )
        assert route(state) == "escalate"
