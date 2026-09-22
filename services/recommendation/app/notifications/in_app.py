from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from app.domain.recommendation import RecommendationResponse
from app.observability import ALERT_DELIVERY_LATENCY_SECONDS
from app.settings import get_settings


class InAppNotificationDispatcher:
    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis = redis_client

    async def get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            settings = get_settings()
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)  # type: ignore[no-untyped-call]
        return self._redis

    async def dispatch_in_app_alert(
        self,
        user_id: str,
        trip_id: str,
        recommendation: RecommendationResponse,
        change_reasons: list[str],
    ) -> dict[str, Any]:
        """Publishes an in-app alert event over Redis for SSE consumption."""
        with ALERT_DELIVERY_LATENCY_SECONDS.labels(channel="IN_APP").time():
            now = datetime.now(UTC)
            event_payload = {
                "event": "trip.alert",
                "user_id": user_id,
                "trip_id": trip_id,
                "recommendation_id": recommendation.recommendation_id,
                "action_code": recommendation.action_code,
                "risk_level": recommendation.risk_level,
                "short_summary": recommendation.short_summary,
                "change_reasons": change_reasons,
                "timestamp": now.isoformat(),
            }

            try:
                r = await self.get_redis()
                channel = f"sta:{get_settings().APP_ENV}:notifications:user:{user_id}"
                await r.publish(channel, json.dumps(event_payload))
                return {"status": "DELIVERED", "channel": "IN_APP", "channel_name": channel}
            except Exception as e:
                return {"status": "FAILED", "channel": "IN_APP", "error": str(e)}
