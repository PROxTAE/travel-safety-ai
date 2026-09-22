from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_live(client: AsyncClient) -> None:
    res = await client.get("/health/live")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "recommendation"


@pytest.mark.asyncio
async def test_health_ready(client: AsyncClient) -> None:
    res = await client.get("/health/ready")
    assert res.status_code in (200, 503)
    data = res.json()
    assert "dependencies" in data


@pytest.mark.asyncio
async def test_metrics(client: AsyncClient) -> None:
    res = await client.get("/metrics")
    assert res.status_code == 200
    assert "recommendation_requests_total" in res.text


@pytest.mark.asyncio
async def test_create_and_get_recommendation_api(
    client: AsyncClient,
    sample_decision: dict[str, Any],
    sample_context: dict[str, Any],
) -> None:
    req_id = str(uuid.uuid4())
    trip_id = str(uuid.uuid4())

    payload = {
        "request_id": req_id,
        "trip_id": trip_id,
        "decision": sample_decision,
        "context": sample_context,
        "locale": "th-TH",
    }

    # 1. Create recommendation (201)
    res = await client.post("/internal/v1/recommendations", json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    assert "data" in body
    assert "meta" in body
    rec_id = body["data"]["recommendation_id"]
    assert body["data"]["action_code"] == "NORMAL"
    assert body["data"]["risk_level"] == "LOW"

    # 2. Idempotent replay with same request_id (200)
    replay_res = await client.post("/internal/v1/recommendations", json=payload)
    assert replay_res.status_code == 200
    replay_body = replay_res.json()
    assert replay_body["data"]["recommendation_id"] == rec_id

    # 3. Get recommendation by ID (200)
    get_res = await client.get(f"/internal/v1/recommendations/{rec_id}")
    assert get_res.status_code == 200
    get_body = get_res.json()
    assert get_body["data"]["recommendation_id"] == rec_id

    # 4. Get non-existent recommendation (404)
    fake_id = str(uuid.uuid4())
    not_found_res = await client.get(f"/internal/v1/recommendations/{fake_id}")
    assert not_found_res.status_code == 404
    err_body = not_found_res.json()
    assert err_body["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_reject_unvalidated_decision_api(
    client: AsyncClient,
    sample_decision: dict[str, Any],
    sample_context: dict[str, Any],
) -> None:
    sample_decision["validation"]["locked_action"] = False
    payload = {
        "request_id": str(uuid.uuid4()),
        "trip_id": str(uuid.uuid4()),
        "decision": sample_decision,
        "context": sample_context,
    }

    res = await client.post("/internal/v1/recommendations", json=payload)
    assert res.status_code == 422
    err_body = res.json()
    assert err_body["error"]["code"] == "POLICY_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_get_emergency_contacts_api(client: AsyncClient) -> None:
    res = await client.get("/internal/v1/emergency/contacts?country_code=TH")
    assert res.status_code == 200
    body = res.json()
    assert "data" in body
    contacts = body["data"]
    assert len(contacts) >= 4
    phones = {c["phone"] for c in contacts}
    assert "191" in phones


@pytest.mark.asyncio
async def test_feedback_and_safety_review_api(client: AsyncClient) -> None:
    rec_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # 1. Submit unsafe feedback
    res = await client.post(
        "/internal/v1/feedback",
        json={
            "user_id": user_id,
            "recommendation_id": rec_id,
            "category": "UNSAFE",
            "text": "Severe hazard at [100.5, 13.7], call 089-999-9999",
        },
    )
    assert res.status_code == 201
    body = res.json()
    event = body["data"]
    assert event["category"] == "UNSAFE"
    assert event["safety_review_id"] is not None
    assert "[COORD_REDACTED]" in event["text_redacted"]
    assert "[PHONE_REDACTED]" in event["text_redacted"]

    review_id = event["safety_review_id"]

    # 2. List safety reviews
    list_res = await client.get("/internal/v1/feedback/safety-review?status=NEW")
    assert list_res.status_code == 200
    list_body = list_res.json()
    assert list_body["page"]["total"] >= 1

    # 3. Transition safety review status
    trans_res = await client.post(
        f"/internal/v1/feedback/safety-review/{review_id}/transition",
        json={
            "status": "TRIAGED",
            "assigned_to": "safety-lead",
            "notes": "Verified with provincial ops",
        },
    )
    assert trans_res.status_code == 200
    trans_body = trans_res.json()
    assert trans_body["data"]["status"] == "TRIAGED"
    assert trans_body["data"]["assigned_to"] == "safety-lead"


@pytest.mark.asyncio
async def test_subscriptions_and_alert_evaluate_api(
    client: AsyncClient,
    sample_decision: dict[str, Any],
    sample_context: dict[str, Any],
) -> None:
    user_id = str(uuid.uuid4())
    trip_id = str(uuid.uuid4())
    consent_id = str(uuid.uuid4())

    # 1. Create subscription (201)
    sub_res = await client.post(
        "/internal/v1/subscriptions",
        json={
            "user_id": user_id,
            "trip_id": trip_id,
            "consent_id": consent_id,
            "channel": "IN_APP",
            "min_severity": "MODERATE",
        },
    )
    assert sub_res.status_code == 201
    sub_body = sub_res.json()
    sub_id = sub_body["data"]["subscription_id"]

    # 2. Evaluate alert escalation
    prev_rec = {
        "recommendation_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "trip_id": trip_id,
        "status": "COMPLETED",
        "action_code": "NORMAL",
        "risk_level": "LOW",
        "confidence": 0.9,
        "short_summary": "Clear route",
        "alerts": [],
        "sources": [],
        "freshness": {"fetched_at": "2026-09-22T00:00:00Z"},
        "limitations": [],
        "degraded_services": [],
        "versions": {"contract": "1.0.0"},
        "created_at": "2026-09-22T00:00:00Z",
    }
    new_rec = {
        "recommendation_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "trip_id": trip_id,
        "status": "COMPLETED",
        "action_code": "AVOID",
        "risk_level": "HIGH",
        "confidence": 0.95,
        "short_summary": "Severe storm closure",
        "alerts": [
            {
                "event_id": "storm-1",
                "event_type": "STORM",
                "title": "Severe Tropical Storm",
                "severity": "SEVERE",
            }
        ],
        "sources": [],
        "freshness": {"fetched_at": "2026-09-22T01:00:00Z"},
        "limitations": [],
        "degraded_services": [],
        "versions": {"contract": "1.0.0"},
        "created_at": "2026-09-22T01:00:00Z",
    }

    eval_res = await client.post(
        "/internal/v1/alerts/evaluate",
        json={
            "trip_id": trip_id,
            "previous_recommendation": prev_rec,
            "new_recommendation": new_rec,
        },
    )
    assert eval_res.status_code == 200
    eval_body = eval_res.json()
    assert eval_body["data"]["meaningful_change"] is True
    assert eval_body["data"]["cooldown_bypassed"] is True

    # 3. Delete subscription (204)
    del_res = await client.delete(f"/internal/v1/subscriptions/{sub_id}")
    assert del_res.status_code == 204
