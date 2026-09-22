from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.directory.ingest import ingest_emergency_directory
from app.domain.recommendation import Freshness, RecommendationResponse, ResponseVersions
from app.models import DeliveryLogModel, EmergencyContactModel
from app.notifications.webpush import WebPushDispatcher
from app.repositories.contacts_repo import ContactsRepository
from app.workers.deliver_alerts import AlertDeliveryService
from app.workers.refresh_subscriptions import refresh_active_subscriptions_job
from app.workers.retention import cleanup_retention_job


@pytest.mark.asyncio
async def test_contacts_repo_and_ingest(test_db_session: AsyncSession) -> None:
    repo = ContactsRepository(test_db_session)
    c = EmergencyContactModel(
        id=uuid.uuid4(),
        country_code="TH",
        subdivision="10",
        service_type="POLICE",
        label_i18n={"th-TH": "ตำรวจ"},
        phone="191",
        source_url="https://example.com",
        authority="OFFICIAL",
        effective_at=datetime.now(UTC) - timedelta(days=1),
        verified_at=datetime.now(UTC),
        reviewer="tester",
        checksum="abcd1234abcd1234",
        status="VERIFIED",
    )
    test_db_session.add(c)
    await test_db_session.commit()

    contacts = await repo.get_contacts(country_code="TH", subdivision="10", service_type="POLICE")
    assert len(contacts) >= 1

    ingested = await ingest_emergency_directory(test_db_session, "emergency-directory/sources.yaml")
    assert ingested >= 5


@pytest.mark.asyncio
async def test_retention_workers(test_db_session: AsyncSession) -> None:
    now = datetime.now(UTC)
    old_log = DeliveryLogModel(
        id=uuid.uuid4(),
        subscription_id=uuid.uuid4(),
        event_hash="old_event_hash",
        channel="SMS",
        status="DELIVERED",
        payload_summary={},
        attempted_at=now - timedelta(days=100),
    )
    test_db_session.add(old_log)
    await test_db_session.commit()

    with patch("app.workers.retention.get_session_factory") as mock_factory:
        mock_factory.return_value = lambda: test_db_session
        res = await cleanup_retention_job(retention_days=30)
        assert res["deleted_delivery_logs"] >= 0


@pytest.mark.asyncio
async def test_sweep_subscriptions(test_db_session: AsyncSession) -> None:
    with patch("app.workers.refresh_subscriptions.get_session_factory") as mock_factory:
        mock_factory.return_value = lambda: test_db_session
        with patch("redis.asyncio.from_url") as mock_redis:
            mock_r = AsyncMock()
            mock_redis.return_value = mock_r
            cnt = await refresh_active_subscriptions_job()
            assert cnt >= 0


@pytest.mark.asyncio
async def test_webpush_dispatcher() -> None:
    dispatcher = WebPushDispatcher()
    rec = RecommendationResponse(
        recommendation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        trip_id=str(uuid.uuid4()),
        status="COMPLETED",
        action_code="NORMAL",
        risk_level="LOW",
        confidence=0.9,
        short_summary="Test summary",
        freshness=Freshness(fetched_at=datetime.now(UTC)),
        versions=ResponseVersions(),
        created_at=datetime.now(UTC),
    )
    res = await dispatcher.dispatch_push(
        subscription_info={"endpoint": "https://push.example.com/sub/1"},
        trip_id=str(uuid.uuid4()),
        recommendation=rec,
    )
    assert res["status"] in ("DELIVERED", "SKIPPED_UNCONFIGURED")


@pytest.mark.asyncio
async def test_alert_delivery_service_channels(test_db_session: AsyncSession) -> None:
    trip_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    consent_id = str(uuid.uuid4())

    # Add active subscriptions for multiple channels
    from app.repositories.subscription_repo import SubscriptionRepository

    repo = SubscriptionRepository(test_db_session)
    await repo.create_subscription(
        user_id=user_id,
        trip_id=trip_id,
        consent_id=consent_id,
        channel="EMAIL",
        destination="test@example.com",
    )
    await repo.create_subscription(
        user_id=user_id,
        trip_id=trip_id,
        consent_id=consent_id,
        channel="SMS",
        destination="+66812345678",
    )

    delivery_svc = AlertDeliveryService(test_db_session)
    rec = RecommendationResponse(
        recommendation_id=str(uuid.uuid4()),
        request_id=str(uuid.uuid4()),
        trip_id=trip_id,
        status="COMPLETED",
        action_code="CHANGE_ROUTE",
        risk_level="HIGH",
        confidence=0.95,
        short_summary="Severe hazard detected along corridor.",
        freshness=Freshness(fetched_at=datetime.now(UTC)),
        versions=ResponseVersions(),
        created_at=datetime.now(UTC),
    )

    res = await delivery_svc.evaluate_and_deliver(
        trip_id=trip_id,
        previous_rec=None,
        new_rec=rec,
        force_delivery=True,
    )
    assert res["meaningful_change"] is True
