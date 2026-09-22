from __future__ import annotations

import json
from typing import Any

from app.domain.recommendation import RecommendationResponse
from app.observability import ALERT_DELIVERY_LATENCY_SECONDS
from app.settings import get_settings


class WebPushDispatcher:
    def __init__(self) -> None:
        self.settings = get_settings()

    def format_payload(
        self,
        trip_id: str,
        recommendation: RecommendationResponse,
    ) -> str:
        """Creates a minimal privacy-safe push payload.

        Guarantees:
        - No exact personal coordinates or sensitive PII on the lockscreen.
        - Direct action prompt to open authenticated app.
        """
        payload = {
            "title": f"Safety Alert: {recommendation.action_code}",
            "body": recommendation.short_summary[:120],
            "data": {
                "trip_id": trip_id,
                "recommendation_id": recommendation.recommendation_id,
                "action_code": recommendation.action_code,
                "url": f"/trips/{trip_id}",
            },
            "tag": f"trip-alert-{trip_id}",
        }
        return json.dumps(payload)

    async def dispatch_push(
        self,
        subscription_info: dict[str, Any] | None,
        trip_id: str,
        recommendation: RecommendationResponse,
    ) -> dict[str, Any]:
        with ALERT_DELIVERY_LATENCY_SECONDS.labels(channel="PUSH").time():
            if not self.settings.VAPID_PRIVATE_KEY or not subscription_info:
                return {
                    "status": "SKIPPED_UNCONFIGURED",
                    "channel": "PUSH",
                    "reason": "VAPID keys or push subscription info not configured.",
                }

            try:
                import pywebpush

                payload = self.format_payload(trip_id, recommendation)
                response = pywebpush.webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=self.settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": self.settings.VAPID_CLAIMS_SUB},
                )
                return {
                    "status": "DELIVERED",
                    "channel": "PUSH",
                    "status_code": response.status_code
                    if hasattr(response, "status_code")
                    else 200,
                }
            except Exception as e:
                return {
                    "status": "FAILED",
                    "channel": "PUSH",
                    "error": str(e),
                }
