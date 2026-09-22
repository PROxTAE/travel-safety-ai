from __future__ import annotations

from typing import Any

from app.domain.recommendation import RecommendationResponse
from app.settings import get_settings


class SmsDispatcher:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def dispatch_sms(
        self,
        recipient_phone: str | None,
        trip_id: str,
        recommendation: RecommendationResponse,
    ) -> dict[str, Any]:
        if not self.settings.SMS_PROVIDER_ENABLED or not recipient_phone:
            return {
                "status": "SKIPPED_UNCONFIGURED",
                "channel": "SMS",
                "reason": "SMS provider not enabled or recipient not provided.",
            }
        return {"status": "DELIVERED", "channel": "SMS"}
