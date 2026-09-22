from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select

from app.database import get_session_factory
from app.models import SubscriptionModel
from app.settings import get_settings


async def refresh_active_subscriptions_job(ctx: dict[str, Any] | None = None) -> int:
    """Scheduled job to discover active subscriptions and request reassessments."""
    settings = get_settings()
    now = datetime.now(UTC)
    factory = get_session_factory()
    reassessment_count = 0

    async with factory() as session:
        query = select(SubscriptionModel).where(
            SubscriptionModel.status == "ACTIVE",
            (SubscriptionModel.expires_at.is_(None)) | (SubscriptionModel.expires_at > now),
        )
        res = await session.execute(query)
        subscriptions = res.scalars().all()

        if not subscriptions:
            return 0

        # Group by trip_id to avoid duplicate reassessment requests for the same trip
        unique_trips: dict[str, str] = {}
        for sub in subscriptions:
            unique_trips[str(sub.trip_id)] = str(sub.user_id)

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)  # type: ignore[no-untyped-call]
        try:
            for trip_id, user_id in unique_trips.items():
                event = {
                    "event_type": "alert.reassessment.requested",
                    "trip_id": trip_id,
                    "user_id": user_id,
                    "reason": "SCHEDULED_REFRESH",
                    "requested_at": now.isoformat(),
                }
                channel = f"sta:{settings.APP_ENV}:events:reassessment"
                await r.publish(channel, json.dumps(event))
                reassessment_count += 1
        finally:
            await r.aclose()

    return reassessment_count
