"""Standalone load testing benchmark for Smart Travel API.

Measures throughput (req/s), latency distributions (p50, p95, p99, min, max, avg),
and error rates under concurrent request loads.

Usage:
  uv run python scripts/load_test.py --url http://localhost:8000 \
    --endpoint /health/live --concurrency 20 --requests 200
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import Any

import httpx


async def _worker(
    client: httpx.AsyncClient,
    url: str,
    queue: asyncio.Queue[int],
    latencies: list[float],
    status_counts: dict[int, int],
    errors: list[str],
) -> None:
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        start = time.perf_counter()
        try:
            resp = await client.get(url)
            elapsed = time.perf_counter() - start
            latencies.append(elapsed * 1000.0)  # ms
            status_counts[resp.status_code] = status_counts.get(resp.status_code, 0) + 1
        except Exception as exc:
            elapsed = time.perf_counter() - start
            errors.append(str(exc))
        finally:
            queue.task_done()


async def run_load_test(
    base_url: str,
    endpoint: str,
    total_requests: int,
    concurrency: int,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{endpoint}"
    queue: asyncio.Queue[int] = asyncio.Queue()
    for i in range(total_requests):
        queue.put_nowait(i)

    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    errors: list[str] = []

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    wall_start = time.perf_counter()

    async with httpx.AsyncClient(limits=limits, timeout=timeout_seconds) as client:
        workers = [
            asyncio.create_task(_worker(client, url, queue, latencies, status_counts, errors))
            for _ in range(concurrency)
        ]
        await asyncio.gather(*workers)

    wall_duration = time.perf_counter() - wall_start

    successful = len(latencies)
    error_count = len(errors)
    throughput = (successful + error_count) / wall_duration if wall_duration > 0 else 0.0

    p50 = statistics.median(latencies) if latencies else 0.0
    p95 = (
        statistics.quantiles(latencies, n=20)[18]
        if len(latencies) >= 20
        else (max(latencies) if latencies else 0.0)
    )
    p99 = (
        statistics.quantiles(latencies, n=100)[98]
        if len(latencies) >= 100
        else (max(latencies) if latencies else 0.0)
    )
    avg_latency = statistics.mean(latencies) if latencies else 0.0
    min_latency = min(latencies) if latencies else 0.0
    max_latency = max(latencies) if latencies else 0.0

    results = {
        "url": url,
        "concurrency": concurrency,
        "total_requests": total_requests,
        "successful_requests": successful,
        "failed_requests": error_count,
        "duration_seconds": round(wall_duration, 4),
        "throughput_req_per_sec": round(throughput, 2),
        "latencies_ms": {
            "min": round(min_latency, 2),
            "avg": round(avg_latency, 2),
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": round(max_latency, 2),
        },
        "status_codes": status_counts,
        "error_samples": errors[:5],
    }
    return results


def print_report(res: dict[str, Any]) -> None:
    print("\n========================================================")
    print(f" Load Test Results for: {res['url']}")
    print("========================================================")
    print(f"Concurrency:       {res['concurrency']}")
    print(f"Total Requests:    {res['total_requests']}")
    print(f"Successful:        {res['successful_requests']}")
    print(f"Failed:            {res['failed_requests']}")
    print(f"Wall Duration:     {res['duration_seconds']} s")
    print(f"Throughput:        {res['throughput_req_per_sec']} req/sec")
    print("--------------------------------------------------------")
    print("Latency Distribution (ms):")
    for k, v in res["latencies_ms"].items():
        print(f"  {k.upper():4s}: {v:8.2f} ms")
    print("--------------------------------------------------------")
    print("Status Codes:")
    for code, count in sorted(res["status_codes"].items()):
        print(f"  HTTP {code}: {count}")
    if res["error_samples"]:
        print("--------------------------------------------------------")
        print("Errors:")
        for err in res["error_samples"]:
            print(f"  - {err}")
    print("========================================================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="API Load Testing Benchmark")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of API")
    parser.add_argument("--endpoint", default="/health/live", help="Endpoint path to test")
    parser.add_argument("--requests", type=int, default=100, help="Total requests to dispatch")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent workers")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout (seconds)")
    args = parser.parse_args()

    results = asyncio.run(
        run_load_test(
            base_url=args.url,
            endpoint=args.endpoint,
            total_requests=args.requests,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout,
        )
    )
    print_report(results)


if __name__ == "__main__":
    main()
