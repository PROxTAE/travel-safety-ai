from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.alerts import AlertSubscription, DeliveryChannel, SeverityLevel
from app.models import DeliveryLogModel, SubscriptionModel
from app.observability import ALERT_DELIVERIES_TOTAL


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_subscription(
        self,
        user_id: str,
        trip_id: str,
        consent_id: str,
        channel: DeliveryChannel,
        destination: str | None = None,
        min_severity: SeverityLevel = "MODERATE",
        expires_at: datetime | None = None,
    ) -> AlertSubscription:
        sub_id = uuid.uuid4()
        now = datetime.now(UTC)

        db_sub = SubscriptionModel(
            id=sub_id,
            user_id=uuid.UUID(user_id),
            trip_id=uuid.UUID(trip_id),
            channel=channel,
            destination=destination,
            consent_id=uuid.UUID(consent_id),
            status="ACTIVE",
            min_severity=min_severity,
            cooldown_until=None,
            expires_at=expires_at,
            created_at=now,
        )
        self.session.add(db_sub)
        await self.session.commit()
        await self.session.refresh(db_sub)

        return AlertSubscription(
            subscription_id=str(db_sub.id),
            user_id=str(db_sub.user_id),
            trip_id=str(db_sub.trip_id),
            channel=cast(Any, db_sub.channel),
            destination=db_sub.destination,
            consent_id=str(db_sub.consent_id),
            status=cast(Any, db_sub.status),
            min_severity=cast(Any, db_sub.min_severity),
            cooldown_until=db_sub.cooldown_until,
            expires_at=db_sub.expires_at,
            created_at=db_sub.created_at,
        )

    async def cancel_subscription(self, subscription_id: uuid.UUID) -> bool:
        now = datetime.now(UTC)
        stmt = (
            update(SubscriptionModel)
            .where(SubscriptionModel.id == subscription_id)
            .values(status="CANCELLED", cancelled_at=now)
        )
        res = await self.session.execute(stmt)
        await self.session.commit()
        return isinstance(res, CursorResult) and res.rowcount > 0

    async def get_active_subscriptions_for_trip(
        self,
        trip_id: uuid.UUID,
    ) -> list[AlertSubscription]:
        now = datetime.now(UTC)
        query = select(SubscriptionModel).where(
            SubscriptionModel.trip_id == trip_id,
            SubscriptionModel.status == "ACTIVE",
            (SubscriptionModel.expires_at.is_(None)) | (SubscriptionModel.expires_at > now),
        )
        res = await self.session.execute(query)
        rows = res.scalars().all()

        return [
            AlertSubscription(
                subscription_id=str(r.id),
                user_id=str(r.user_id),
                trip_id=str(r.trip_id),
                channel=cast(Any, r.channel),
                destination=r.destination,
                consent_id=str(r.consent_id),
                status=cast(Any, r.status),
                min_severity=cast(Any, r.min_severity),
                cooldown_until=r.cooldown_until,
                expires_at=r.expires_at,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def update_cooldown(
        self,
        subscription_id: uuid.UUID,
        cooldown_until: datetime,
    ) -> None:
        stmt = (
            update(SubscriptionModel)
            .where(SubscriptionModel.id == subscription_id)
            .values(cooldown_until=cooldown_until)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def log_delivery(
        self,
        subscription_id: uuid.UUID | None,
        event_hash: str,
        channel: str,
        status: str,
        payload_summary: dict[str, Any],
        provider_message_id: str | None = None,
        error_message: str | None = None,
    ) -> DeliveryLogModel:
        now = datetime.now(UTC)
        # Check if already delivered (idempotency by subscription_id and event_hash)
        query = select(DeliveryLogModel).where(
            DeliveryLogModel.event_hash == event_hash,
            DeliveryLogModel.subscription_id == subscription_id,
        )
        existing_res = await self.session.execute(query)
        existing = existing_res.scalars().first()

        if existing:
            return existing

        log_entry = DeliveryLogModel(
            id=uuid.uuid4(),
            subscription_id=subscription_id,
            event_hash=event_hash,
            channel=channel,
            status=status,
            provider_message_id=provider_message_id,
            payload_summary=payload_summary,
            attempted_at=now,
            delivered_at=now if status == "DELIVERED" else None,
            error_message=error_message,
        )
        self.session.add(log_entry)
        await self.session.commit()
        await self.session.refresh(log_entry)

        ALERT_DELIVERIES_TOTAL.labels(channel=channel, status=status).inc()
        return log_entry
