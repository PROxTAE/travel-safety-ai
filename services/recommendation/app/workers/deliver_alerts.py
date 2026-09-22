from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.alerts import (
    COOLDOWN_DURATIONS,
    compute_event_hash,
    detect_meaningful_change,
    should_deliver_notification,
)
from app.domain.recommendation import RecommendationResponse
from app.notifications.email import EmailDispatcher
from app.notifications.in_app import InAppNotificationDispatcher
from app.notifications.sms import SmsDispatcher
from app.notifications.webpush import WebPushDispatcher
from app.observability import ALERT_EVALUATIONS_TOTAL
from app.repositories.subscription_repo import SubscriptionRepository


class AlertDeliveryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SubscriptionRepository(session)
        self.in_app = InAppNotificationDispatcher()
        self.webpush = WebPushDispatcher()
        self.email = EmailDispatcher()
        self.sms = SmsDispatcher()

    async def evaluate_and_deliver(
        self,
        trip_id: str,
        previous_rec: RecommendationResponse | None,
        new_rec: RecommendationResponse,
        force_delivery: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        change_result = detect_meaningful_change(previous_rec, new_rec)

        ALERT_EVALUATIONS_TOTAL.labels(
            meaningful_change="true" if change_result.is_meaningful else "false"
        ).inc()

        delivered_channels: list[str] = []
        suppressed_channels: list[str] = []

        if not change_result.is_meaningful and not force_delivery:
            return {
                "meaningful_change": False,
                "change_reasons": [],
                "delivered_channels": [],
                "suppressed_channels": [],
                "cooldown_bypassed": False,
                "event_hash": "",
            }

        # Calculate unique event hash
        alert_ids = [a.event_id for a in new_rec.alerts]
        event_hash = compute_event_hash(
            trip_id=trip_id,
            action_code=new_rec.action_code,
            risk_level=new_rec.risk_level,
            alert_ids=alert_ids,
            version="1.0.0",
        )

        trip_uuid = uuid.UUID(trip_id)
        subscriptions = await self.repo.get_active_subscriptions_for_trip(trip_uuid)

        for sub in subscriptions:
            can_deliver, suppress_reason = should_deliver_notification(sub, change_result, now)
            sub_uuid = uuid.UUID(sub.subscription_id)

            if can_deliver or force_delivery:
                status = "FAILED"
                payload_summary = {
                    "action_code": new_rec.action_code,
                    "risk_level": new_rec.risk_level,
                    "summary": new_rec.short_summary,
                    "reasons": change_result.reasons,
                }

                if sub.channel == "IN_APP":
                    res = await self.in_app.dispatch_in_app_alert(
                        user_id=sub.user_id,
                        trip_id=trip_id,
                        recommendation=new_rec,
                        change_reasons=change_result.reasons,
                    )
                    status = res.get("status", "FAILED")
                elif sub.channel == "PUSH":
                    res = await self.webpush.dispatch_push(
                        subscription_info={"endpoint": sub.destination}
                        if sub.destination
                        else None,
                        trip_id=trip_id,
                        recommendation=new_rec,
                    )
                    status = res.get("status", "FAILED")
                elif sub.channel == "EMAIL":
                    res = await self.email.dispatch_email(
                        recipient_email=sub.destination,
                        trip_id=trip_id,
                        recommendation=new_rec,
                    )
                    status = res.get("status", "FAILED")
                elif sub.channel == "SMS":
                    res = await self.sms.dispatch_sms(
                        recipient_phone=sub.destination,
                        trip_id=trip_id,
                        recommendation=new_rec,
                    )
                    status = res.get("status", "FAILED")

                # Update subscription cooldown only if delivery succeeded or was dry-run/mock
                if status in ("DELIVERED", "SKIPPED_UNCONFIGURED"):
                    cooldown_dur = COOLDOWN_DURATIONS.get(
                        new_rec.risk_level, COOLDOWN_DURATIONS["MODERATE"]
                    )
                    await self.repo.update_cooldown(sub_uuid, now + cooldown_dur)
                    delivered_channels.append(sub.channel)
                else:
                    suppressed_channels.append(f"{sub.channel}: delivery failed")

                # Log delivery idempotently
                await self.repo.log_delivery(
                    subscription_id=sub_uuid,
                    event_hash=f"{event_hash}:{sub.channel}",
                    channel=sub.channel,
                    status=status,
                    payload_summary=payload_summary,
                )
            else:
                suppressed_channels.append(f"{sub.channel}: {suppress_reason}")

        return {
            "meaningful_change": change_result.is_meaningful,
            "change_reasons": change_result.reasons,
            "delivered_channels": delivered_channels,
            "suppressed_channels": suppressed_channels,
            "cooldown_bypassed": change_result.cooldown_bypass_required,
            "event_hash": event_hash,
        }
