"""Corridor query and snapshot pipeline timings at volume; run by hand, not by pytest.

    docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration \
        uv run python tests/perf_corridor.py --events 50000

Creates a throwaway database from TEST_DATABASE_URL, seeds it through
load_seed.py, prints EXPLAIN ANALYZE with and without the geography index plus
p50/p95 timings, and drops the database.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from load_seed import ROUTE, WINDOW_END, WINDOW_START, seed_disasters
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.canonical import DisasterEvent, GeoLineString, RouteCandidate, WeatherForecastPoint
from app.domain.snapshot import TravelWindow
from app.pipeline.build import RouteEvidence, build_route_snapshot
from app.pipeline.corridor import sample_route
from app.pipeline.spatial import HAZARD_QUERY, corridor_geojson
from app.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures"


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def record(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


async def measure(url: str, events: int, runs: int, corridor_events: int) -> None:
    engine = create_async_engine(url)
    samples = sample_route(
        GeoLineString(type="LineString", coordinates=ROUTE),
        departure_at=WINDOW_START,
        duration_seconds=(WINDOW_END - WINDOW_START).total_seconds(),
        max_spacing_m=1000,
    )
    params = {
        "route": corridor_geojson(samples),
        "radius_m": 5000,
        "start_at": WINDOW_START,
        "end_at": WINDOW_END,
    }
    async with AsyncSession(engine) as session:
        started = time.perf_counter()
        await seed_disasters(session, events)
        await session.commit()
        print(f"seeded {events} disaster rows in {time.perf_counter() - started:.1f}s")
        for label, setup in (
            ("with geography index", []),
            ("index disabled", ["SET enable_indexscan = off", "SET enable_bitmapscan = off"]),
            ("forced custom plan", ["SET plan_cache_mode = force_custom_plan"]),
        ):
            for statement in setup:
                await session.execute(text(statement))
            plan = await session.execute(
                text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + HAZARD_QUERY), params
            )
            print(f"\n--- EXPLAIN ANALYZE, {label} ---")
            print("\n".join(row[0] for row in plan))
            timings = []
            for _ in range(runs):
                started = time.perf_counter()
                matched = len((await session.execute(text(HAZARD_QUERY), params)).all())
                timings.append((time.perf_counter() - started) * 1000)
            print(
                f"{label}: {matched} rows, p50 {statistics.median(timings):.1f} ms, "
                f"p95 {percentile(timings, 0.95):.1f} ms over {runs} runs"
            )
            await session.execute(text("RESET ALL"))

        base = RouteCandidate.model_validate(record("m04-route-candidates.json"))
        route = base.model_copy(
            update={"geometry": GeoLineString(type="LineString", coordinates=ROUTE)}
        )
        quake = record("m04-usgs-event.json")
        disasters = [
            DisasterEvent.model_validate(
                quake
                | {
                    "event_id": f"load-{i}",
                    "geometry": {"type": "Point", "coordinates": [99.5 + i * 0.001, 16.0]},
                    "source": quake["source"] | {"source_id": f"load:{i}"},
                }
            )
            for i in range(corridor_events)
        ]
        weather = [WeatherForecastPoint.model_validate(record("m04-weather-forecast-points.json"))]
        evidence = RouteEvidence(
            route, weather, disasters, [], {"route": route.quality, "weather": weather[0].quality}
        )
        window = TravelWindow(starts_at=WINDOW_START, ends_at=WINDOW_END, timezone="Asia/Bangkok")
        timings = []
        for _ in range(runs):
            started = time.perf_counter()
            await build_route_snapshot(
                session,
                snapshot_id=uuid4(),
                request_id=uuid4(),
                trip_id=uuid4(),
                supersedes_snapshot_id=None,
                travel_window=window,
                recommendation_at=datetime(2026, 9, 20, 18, tzinfo=UTC),
                evidence=evidence,
                settings=get_settings(),
                created_at=datetime.now(UTC),
            )
            timings.append((time.perf_counter() - started) * 1000)
        await session.rollback()
        print(
            f"\nsnapshot pipeline, {len(samples)} samples, {corridor_events} corridor events: "
            f"p50 {statistics.median(timings):.1f} ms, p95 {percentile(timings, 0.95):.1f} ms "
            f"over {runs} runs"
        )
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Corridor and snapshot timings at volume.")
    parser.add_argument("--events", type=int, default=50000)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--corridor-events", type=int, default=200)
    args = parser.parse_args()
    maintenance = os.environ["TEST_DATABASE_URL"]
    database = f"integration_perf_{uuid4().hex}"
    admin = create_engine(maintenance, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    os.environ["POSTGRES_DB"] = database
    get_settings.cache_clear()
    try:
        command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
        url = make_url(maintenance).set(database=database, drivername="postgresql+asyncpg")
        asyncio.run(
            measure(
                url.render_as_string(hide_password=False),
                args.events,
                args.runs,
                args.corridor_events,
            )  # fmt: skip
        )
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    main()
