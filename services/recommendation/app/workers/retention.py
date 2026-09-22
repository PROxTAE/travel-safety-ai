from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, update

from app.database import get_session_factory
from app.models import DeliveryLogModel, SubscriptionModel


async def cleanup_retention_job(
    ctx: dict[str, Any] | None = None,
    retention_days: int = 90,
) -> dict[str, int]:
    """Cleans up expired delivery logs and updates expired subscriptions."""
    factory = get_session_factory()
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)

    async with factory() as session:
        # 1. Update expired subscriptions
        sub_stmt = (
            update(SubscriptionModel)
            .where(
                SubscriptionModel.status == "ACTIVE",
                SubscriptionModel.expires_at.is_not(None),
                SubscriptionModel.expires_at <= now,
            )
            .values(status="EXPIRED")
        )
        sub_res = await session.execute(sub_stmt)
        expired_subs = sub_res.rowcount  # type: ignore[attr-defined]

        # 2. Delete ancient delivery logs
        log_stmt = delete(DeliveryLogModel).where(DeliveryLogModel.attempted_at <= cutoff)
        log_res = await session.execute(log_stmt)
        deleted_logs = log_res.rowcount  # type: ignore[attr-defined]

        await session.commit()

        return {
            "expired_subscriptions_updated": expired_subs,
            "deleted_delivery_logs": deleted_logs,
        }
