from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")


def _consume_cancelled_task(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


async def hard_timeout(  # noqa: UP047 - repository CI still compiles with Python 3.11
    coroutine: Coroutine[Any, Any, _T], seconds: float
) -> _T:
    """Bound an I/O operation without waiting for a stalled driver's cancellation."""
    task = asyncio.create_task(coroutine)
    done, _pending = await asyncio.wait({task}, timeout=seconds)
    if task in done:
        return task.result()
    task.cancel()
    task.add_done_callback(_consume_cancelled_task)
    raise TimeoutError
