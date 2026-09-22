from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.domain.recommendation import (
    Freshness,
    RecommendationResponse,
    ResponseVersions,
    RouteCandidate,
)
from app.notifications.email import EmailDispatcher
from app.notifications.sms import SmsDispatcher
from app.notifications.webpush import WebPushDispatcher


def make_dummy_rec() -> RecommendationResponse:
    now = datetime.now(UTC)
    return RecommendationResponse(
        recommendation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        trip_id=str(uuid.uuid4()),
        status="COMPLETED",
        action_code="CHANGE_ROUTE",
        risk_level="HIGH",
        confidence=0.91,
        short_summary="Severe tropical storm approaching route. Use safer route.",
        primary_route=RouteCandidate(route_id=str(uuid.uuid4())),
        alerts=[],
        sources=[],
        freshness=Freshness(fetched_at=now),
        versions=ResponseVersions(),
        created_at=now,
    )


def test_webpush_privacy_payload() -> None:
    dispatcher = WebPushDispatcher()
    rec = make_dummy_rec()
    trip_id = str(uuid.uuid4())

    payload_str = dispatcher.format_payload(trip_id, rec)
    payload = json.loads(payload_str)

    assert "title" in payload
    assert "CHANGE_ROUTE" in payload["title"]
    assert "body" in payload
    assert "data" in payload
    assert payload["data"]["trip_id"] == trip_id
    assert payload["data"]["action_code"] == "CHANGE_ROUTE"
    # Ensure sensitive personal details or medical notes are absent
    assert "medical" not in payload_str.lower()
    assert "phone" not in payload_str.lower()


@pytest.mark.asyncio
async def test_email_sms_unconfigured_graceful_degradation() -> None:
    email_disp = EmailDispatcher()
    sms_disp = SmsDispatcher()
    rec = make_dummy_rec()

    email_res = await email_disp.dispatch_email(
        recipient_email="test@example.com",
        trip_id=rec.trip_id,
        recommendation=rec,
    )
    assert email_res["status"] == "SKIPPED_UNCONFIGURED"

    sms_res = await sms_disp.dispatch_sms(
        recipient_phone="+66812345678",
        trip_id=rec.trip_id,
        recommendation=rec,
    )
    assert sms_res["status"] == "SKIPPED_UNCONFIGURED"
