"""Unit tests for each Phase 1 node, called directly (no compiled graph needed)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.budgets import NodeFn, NodeNotImplementedError
from app.graph.nodes.build_evidence import build_evidence
from app.graph.nodes.check_required_fields import check_required_fields
from app.graph.nodes.degraded_or_escalate import degraded_or_escalate
from app.graph.nodes.emergency_shortcut import emergency_shortcut
from app.graph.nodes.fetch_external_data import fetch_external_data
from app.graph.nodes.finalize import finalize
from app.graph.nodes.format_recommendation import format_recommendation
from app.graph.nodes.integrate_data import integrate_data
from app.graph.nodes.make_decision import make_decision
from app.graph.nodes.validate_evidence import validate_evidence
from app.graph.nodes.validate_final_contract import validate_final_contract
from app.graph.nodes.validate_input import validate_input
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
    ResultSection,
    RunStatus,
    TravelRequest,
    VersionsSection,
)


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


def _request(
    *,
    question: str | None = None,
    origin_confirmed: bool = True,
    destination_confirmed: bool = True,
) -> TravelRequest:
    now = datetime.now(UTC)
    return TravelRequest(
        request_id=uuid.uuid4(),
        trip_id=uuid.uuid4(),
        origin=_location(origin_confirmed),
        destination=_location(destination_confirmed),
        departure_time=now + timedelta(hours=1),
        travel_modes=["TRAIN"],
        question=question,
        locale="th-TH",
        timezone="Asia/Bangkok",
    )


def _state(
    request: TravelRequest | None = None,
    *,
    result: ResultSection | None = None,
    quality: QualitySection | None = None,
) -> AgentState:
    now = datetime.now(UTC)
    request = request or _request()
    return AgentState(
        identity=IdentitySection(
            request_id=request.request_id,
            correlation_id=uuid.uuid4(),
            trip_id=request.trip_id,
            user_scope_hash="h",
        ),
        input=InputSection(travel_request=request),
        plan=PlanSection(graph_version="0.1.0"),
        result=result or ResultSection(),
        quality=quality or QualitySection(),
        control=ControlSection(started_at=now, deadline_at=now + timedelta(seconds=45)),
        versions=VersionsSection(contract="1.0.0", graph="0.1.0"),
    )


class TestValidateInput:
    async def test_passes_when_identity_matches_the_request(self) -> None:
        assert await validate_input(_state()) == {}

    async def test_fails_when_request_id_does_not_match(self) -> None:
        state = _state()
        mismatched = state.model_copy(
            update={"identity": state.identity.model_copy(update={"request_id": uuid.uuid4()})}
        )
        result = await validate_input(mismatched)
        assert result["control_patch"]["status"] is RunStatus.FAILED  # type: ignore[index]
        assert result["control_patch"]["errors"] == ["VALIDATION_ERROR"]  # type: ignore[index]


class TestCheckRequiredFields:
    async def test_confirmed_locations_have_nothing_missing(self) -> None:
        result = await check_required_fields(_state())
        assert result["input"].missing_fields == []  # type: ignore[union-attr]
        assert "control_patch" not in result

    async def test_unconfirmed_origin_is_reported_missing(self) -> None:
        state = _state(_request(origin_confirmed=False))
        result = await check_required_fields(state)
        assert result["input"].missing_fields == ["origin.confirmed_by_user"]  # type: ignore[union-attr]
        assert result["control_patch"]["status"] is RunStatus.NEEDS_INPUT  # type: ignore[index]

    async def test_both_unconfirmed_reports_both(self) -> None:
        state = _state(_request(origin_confirmed=False, destination_confirmed=False))
        result = await check_required_fields(state)
        assert result["input"].missing_fields == [  # type: ignore[union-attr]
            "origin.confirmed_by_user",
            "destination.confirmed_by_user",
        ]


@pytest.mark.parametrize(
    "node",
    [
        fetch_external_data,
        integrate_data,
        build_evidence,
        degraded_or_escalate,
        make_decision,
        format_recommendation,
        emergency_shortcut,
    ],
)
async def test_unimplemented_nodes_raise_not_implemented(node: NodeFn) -> None:
    with pytest.raises(NodeNotImplementedError):
        await node(_state())


class TestValidateEvidence:
    async def test_sufficient_evidence_is_a_no_op(self) -> None:
        state = _state(quality=QualitySection(freshness=DataStatus.FRESH))
        assert await validate_evidence(state) == {}

    async def test_stale_freshness_increments_the_retry_counter(self) -> None:
        state = _state(quality=QualitySection(freshness=DataStatus.STALE))
        result = await validate_evidence(state)
        assert result["control_patch"]["evidence_retry_count"] == 1  # type: ignore[index]

    async def test_missing_flag_increments_the_retry_counter(self) -> None:
        state = _state(quality=QualitySection(quality_flags=[QualityFlag.MISSING]))
        result = await validate_evidence(state)
        assert result["control_patch"]["evidence_retry_count"] == 1  # type: ignore[index]

    async def test_counter_keeps_incrementing_on_repeated_insufficiency(self) -> None:
        state = _state(quality=QualitySection(freshness=DataStatus.STALE))
        state = state.model_copy(
            update={"control": state.control.model_copy(update={"evidence_retry_count": 1})}
        )
        result = await validate_evidence(state)
        assert result["control_patch"]["evidence_retry_count"] == 2  # type: ignore[index]

    async def test_a_conflicting_flag_that_is_not_missing_or_incomplete_is_still_fine(
        self,
    ) -> None:
        """CONFLICTING alone (without STALE/UNAVAILABLE freshness or a MISSING/INCOMPLETE flag)
        is not, by this node's rule, insufficient — conflicts are `degraded_or_escalate`'s job to
        weigh, not a reason to retry the same fetch."""
        state = _state(quality=QualitySection(quality_flags=[QualityFlag.CONFLICTING]))
        assert await validate_evidence(state) == {}


class TestValidateFinalContract:
    async def test_fails_without_a_recommendation_id(self) -> None:
        result = await validate_final_contract(_state())
        assert result["control_patch"]["status"] is RunStatus.FAILED  # type: ignore[index]
        assert result["control_patch"]["errors"] == ["POLICY_VALIDATION_FAILED"]  # type: ignore[index]

    async def test_passes_with_a_recommendation_id(self) -> None:
        state = _state(result=ResultSection(recommendation_id=uuid.uuid4()))
        assert await validate_final_contract(state) == {}


class TestFinalize:
    async def test_completed_when_nothing_is_degraded(self) -> None:
        result = await finalize(_state())
        assert result["control_patch"]["status"] is RunStatus.COMPLETED  # type: ignore[index]

    async def test_partial_when_a_service_is_degraded(self) -> None:
        state = _state(quality=QualitySection(degraded_services=["external-data"]))
        result = await finalize(state)
        assert result["control_patch"]["status"] is RunStatus.PARTIAL  # type: ignore[index]

    async def test_partial_when_a_quality_flag_is_set(self) -> None:
        state = _state(quality=QualitySection(quality_flags=[QualityFlag.STALE]))
        result = await finalize(state)
        assert result["control_patch"]["status"] is RunStatus.PARTIAL  # type: ignore[index]
