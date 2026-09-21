"""Readiness checks.

Liveness and readiness answer different questions and must not be conflated. Liveness asks whether
the process is running; if it also probed the database, a brief outage would restart every healthy
container and turn a recoverable blip into an outage of its own. Readiness asks whether this
instance can serve traffic right now, so it does probe dependencies — and a failure there takes the
instance out of rotation instead of letting it answer requests it cannot honour.

Every check is bounded twice: individually, and by a budget for the whole probe. An unbounded check
against a hung dependency would hang the probe, and a probe that never answers is read by the
orchestrator as a dead container.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from app.observability.logging import get_logger
from app.observability.metrics import dependency_check_duration_seconds, dependency_up

logger = get_logger(__name__)

CheckStatus = Literal["up", "down", "degraded", "skipped"]


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    required: bool
    status: CheckStatus
    duration_ms: float
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DependencyCheck:
    """One probe.

    `required` decides whether a failure makes the service unready. The database and Redis are
    required: without them the API cannot honour a single request. The agent is not — the API can
    still serve profiles and trips while assessments are unavailable, and reporting that as
    unready would take the whole surface down for a partial outage.
    """

    name: str
    required: bool
    probe: Callable[[], Awaitable[None]]
    timeout_seconds: float


async def run_check(check: DependencyCheck) -> CheckResult:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(check.probe(), timeout=check.timeout_seconds)
        status: CheckStatus = "up"
        detail = None
    except TimeoutError:
        status = "down"
        detail = f"did not answer within {check.timeout_seconds:g}s"
    except Exception as exc:
        status = "down"
        # The exception type only. Its message can carry a DSN, a host name or a credential, and
        # this value is returned to an unauthenticated caller.
        detail = f"unavailable ({type(exc).__name__})"

    duration = time.perf_counter() - started
    dependency_check_duration_seconds.labels(dependency=check.name).observe(duration)
    dependency_up.labels(dependency=check.name, required=str(check.required).lower()).set(
        1 if status == "up" else 0
    )

    if status != "up":
        logger.warning(
            "dependency_check_failed",
            event_type="dependency_check",
            dependency=check.name,
            required=check.required,
            detail=detail,
            duration_ms=round(duration * 1000, 2),
        )

    return CheckResult(
        name=check.name,
        required=check.required,
        status=status,
        duration_ms=round(duration * 1000, 2),
        detail=detail,
    )


async def run_all(
    checks: list[DependencyCheck], *, budget_seconds: float
) -> tuple[bool, list[CheckResult]]:
    """Run every check concurrently inside one budget.

    Returns `(ready, results)`. Checks that do not finish inside the budget are reported as down
    rather than dropped: an answer that omits a slow dependency would look healthier than reality.
    """
    if not checks:
        return True, []

    tasks = [asyncio.create_task(run_check(check)) for check in checks]
    done, pending = await asyncio.wait(tasks, timeout=budget_seconds)

    for task in pending:
        task.cancel()

    results = [task.result() for task in tasks if task in done]
    by_name = {result.name: result for result in results}

    for check in checks:
        if check.name not in by_name:
            by_name[check.name] = CheckResult(
                name=check.name,
                required=check.required,
                status="down",
                duration_ms=round(budget_seconds * 1000, 2),
                detail="exceeded the readiness budget",
            )
            dependency_up.labels(dependency=check.name, required=str(check.required).lower()).set(0)

    ordered = [by_name[check.name] for check in checks]
    ready = all(result.status == "up" for result in ordered if result.required)
    return ready, ordered
