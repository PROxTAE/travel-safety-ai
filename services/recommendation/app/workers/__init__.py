from __future__ import annotations

from typing import Any

from arq.cron import cron

from app.settings import get_settings
from app.workers.deliver_alerts import AlertDeliveryService
from app.workers.refresh_subscriptions import refresh_active_subscriptions_job
from app.workers.retention import cleanup_retention_job

__all__ = [
    "AlertDeliveryService",
    "WorkerSettings",
    "cleanup_retention_job",
    "refresh_active_subscriptions_job",
]


async def startup(ctx: dict[str, Any]) -> None:
    pass


async def shutdown(ctx: dict[str, Any]) -> None:
    pass


class WorkerSettings:
    functions = [refresh_active_subscriptions_job, cleanup_retention_job]
    cron_jobs = [
        # Refresh active subscriptions every 5 minutes
        cron(
            refresh_active_subscriptions_job, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
        ),
        # Retention cleanup once daily at 02:00
        cron(cleanup_retention_job, hour=2, minute=0),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_settings().REDIS_URL
