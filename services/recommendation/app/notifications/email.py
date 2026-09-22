from __future__ import annotations

from typing import Any

from app.domain.recommendation import RecommendationResponse
from app.settings import get_settings


class EmailDispatcher:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def dispatch_email(
        self,
        recipient_email: str | None,
        trip_id: str,
        recommendation: RecommendationResponse,
    ) -> dict[str, Any]:
        if not self.settings.EMAIL_PROVIDER_ENABLED or not recipient_email:
            return {
                "status": "SKIPPED_UNCONFIGURED",
                "channel": "EMAIL",
                "reason": "Email provider not enabled or recipient not provided.",
            }
        return {"status": "DELIVERED", "channel": "EMAIL"}
