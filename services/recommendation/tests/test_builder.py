from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.builders.recommendation_builder import PolicyValidationError, RecommendationBuilder


@pytest.mark.asyncio
async def test_build_normal_recommendation(
    test_db_session: AsyncSession,
    sample_decision: dict[str, Any],
    sample_context: dict[str, Any],
) -> None:
    builder = RecommendationBuilder(test_db_session)
    req_id = str(uuid.uuid4())
    trip_id = str(uuid.uuid4())

    response = await builder.build_recommendation(
        request_id=req_id,
        trip_id=trip_id,
        decision=sample_decision,
        context=sample_context,
    )

    assert response.request_id == req_id
    assert response.trip_id == trip_id
    assert response.action_code == "NORMAL"
    assert response.risk_level == "LOW"
    assert response.confidence == 0.95
    assert response.status == "COMPLETED"
    assert response.primary_route is not None
    assert response.primary_route.route_id == sample_decision["selected_route_id"]
    assert len(response.official_contacts) > 0
    # Thailand emergency contacts present
    assert any(c.phone == "191" for c in response.official_contacts)
    assert response.freshness.expires_at is not None


@pytest.mark.asyncio
async def test_build_change_route_recommendation(
    test_db_session: AsyncSession,
    sample_decision: dict[str, Any],
    sample_context: dict[str, Any],
) -> None:
    builder = RecommendationBuilder(test_db_session)
    sample_decision["action_code"] = "CHANGE_ROUTE"
    sample_decision["risk_level"] = "MEDIUM"
    sample_decision["summary"] = "Use alternative route to avoid heavy rain."

    safer_route_id = str(uuid.uuid4())
    sample_decision["selected_route_id"] = safer_route_id
    sample_context["routes"].append(
        {
            "route_id": safer_route_id,
            "provider_route_id": "ors-safer",
            "label": "RECOMMENDED",
            "mode": "CAR",
            "exposure": {"score": 0.05, "closed": False},
            "risk_level": "LOW",
        }
    )

    response = await builder.build_recommendation(
        request_id=str(uuid.uuid4()),
        trip_id=str(uuid.uuid4()),
        decision=sample_decision,
        context=sample_context,
    )

    assert response.action_code == "CHANGE_ROUTE"
    assert response.risk_level == "MEDIUM"
    assert response.primary_route is not None
    assert response.primary_route.route_id == safer_route_id


@pytest.mark.asyncio
async def test_build_avoid_recommendation_and_closed_route(
    test_db_session: AsyncSession,
    sample_decision: dict[str, Any],
    sample_context: dict[str, Any],
) -> None:
    builder = RecommendationBuilder(test_db_session)
    sample_decision["action_code"] = "AVOID"
    sample_decision["risk_level"] = "HIGH"
    sample_decision["summary"] = "Official road closure active."

    response = await builder.build_recommendation(
        request_id=str(uuid.uuid4()),
        trip_id=str(uuid.uuid4()),
        decision=sample_decision,
        context=sample_context,
    )

    assert response.action_code == "AVOID"
    assert response.risk_level == "HIGH"
    # Route cannot remain RECOMMENDED when action is AVOID
    if response.primary_route:
        assert response.primary_route.label != "RECOMMENDED"


@pytest.mark.asyncio
async def test_reject_tampered_decision_locked_action_false(
    test_db_session: AsyncSession,
    sample_decision: dict[str, Any],
    sample_context: dict[str, Any],
) -> None:
    builder = RecommendationBuilder(test_db_session)
    sample_decision["validation"]["locked_action"] = False

    with pytest.raises(PolicyValidationError, match="locked_action validation is false"):
        await builder.build_recommendation(
            request_id=str(uuid.uuid4()),
            trip_id=str(uuid.uuid4()),
            decision=sample_decision,
            context=sample_context,
        )


@pytest.mark.asyncio
async def test_expiration_calculation_from_sources(
    test_db_session: AsyncSession,
    sample_decision: dict[str, Any],
    sample_context: dict[str, Any],
) -> None:
    builder = RecommendationBuilder(test_db_session)
    now = datetime.now(UTC)
    earliest_exp = now + timedelta(minutes=45)

    sample_context["sources"] = [
        {
            "source_id": str(uuid.uuid4()),
            "provider": "open_meteo",
            "authority": "OFFICIAL",
            "fetched_at": now.isoformat(),
            "expires_at": earliest_exp.isoformat(),
        },
        {
            "source_id": str(uuid.uuid4()),
            "provider": "usgs",
            "authority": "OFFICIAL",
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=3)).isoformat(),
        },
    ]

    response = await builder.build_recommendation(
        request_id=str(uuid.uuid4()),
        trip_id=str(uuid.uuid4()),
        decision=sample_decision,
        context=sample_context,
    )

    assert response.freshness.expires_at is not None
    # Expiration matches the earliest source expiration
    assert abs((response.freshness.expires_at - earliest_exp).total_seconds()) < 5
