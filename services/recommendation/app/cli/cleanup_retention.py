from __future__ import annotations

import argparse
import asyncio
import sys

from app.workers.retention import cleanup_retention_job


async def run_cleanup(retention_days: int) -> int:
    print(f"Running data retention cleanup (cutoff: {retention_days} days)...")
    res = await cleanup_retention_job(retention_days=retention_days)
    print(f" Cleanup result: {res}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run data retention cleanup.")
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Retention period in days (default: 90)",
    )
    args = parser.parse_args()
    code = asyncio.run(run_cleanup(args.days))
    sys.exit(code)


if __name__ == "__main__":
    main()
