from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def _consume_cancelled_task(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


async def hard_timeout[T](coroutine: Coroutine[Any, Any, T], seconds: float) -> T:
    """Bound an I/O operation without waiting for a stalled driver's cancellation."""
    task = asyncio.create_task(coroutine)
    done, _pending = await asyncio.wait({task}, timeout=seconds)
    if task in done:
        return task.result()
    task.cancel()
    task.add_done_callback(_consume_cancelled_task)
    raise TimeoutError
