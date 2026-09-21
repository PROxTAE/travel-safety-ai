from __future__ import annotations

import asyncio
import json

from app.runtime import RuntimeState
from app.settings import get_settings


async def _run() -> int:
    runtime = RuntimeState(get_settings())
    try:
        status = await runtime.refresh_model()
        print(
            json.dumps(
                {
                    "status": status.status,
                    "reason": status.reason,
                    "model": status.model.model_dump(mode="json") if status.model else None,
                },
                sort_keys=True,
            )
        )
        return 0 if status.status == "AVAILABLE" else 2
    finally:
        await runtime.close()


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
