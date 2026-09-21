"""Live end-to-end run: module 04 providers -> canonical store -> corridor -> snapshot.

Needs the external-data service running and network access; run by hand:

    docker compose -f compose.yaml -f compose.dev.yaml run --rm data-integration \
        uv run python tests/e2e_live.py --database m05_e2e --keep

Weather and disaster records are live answers from module 04. Route geometry is
not live: openrouteservice has no credential on this machine (P0-08), so the
Bangkok route is the captured openrouteservice record and the other two are
test-only lines on captured coordinates. Prints one JSON summary line per route.
"""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app.domain.canonical import GeoLineString
from app.main import create_app
from app.pipeline.corridor import sample_route
from app.pipeline.spatial import hazard_ids_in_corridor
from app.repositories.canonical_repo import CanonicalRepository
from app.repositories.db import build_engine, build_session_factory, unit_of_work
from app.repositories.models import CanonicalRecord
from app.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures"
MODULE_04 = os.environ.get("MODULE_04_URL", "http://external-data:8002")
ROUTES = [
    # (name, timezone, coordinates or None for the captured geometry, duration seconds)
    ("bangkok-captured-ors", "Asia/Bangkok", None, None),
    ("fiji-dateline-test-line", "Pacific/Fiji", [(179.57103, -16.55536), (-179.82872, -16.414762)],
     3600),
    ("los-angeles-test-line", "America/Los_Angeles", [(-118.2437, 34.0522), (-118.4085, 33.9416)],
     3600),
]  # fmt: skip


def record(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["records"][0]


def source_quality(outcome: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Module 04 reports quality per record, not per capability; derive it openly."""
    if outcome != "ANSWERED":
        return None
    if records:
        stale = [r["quality"] for r in records if r["quality"]["status"] == "STALE"]
        return stale[0] if stale else records[0]["quality"]
    return {
        "status": "FRESH",
        "flags": [],
        "notes": ["derived by the e2e script: capability ANSWERED with no records"],
    }


async def run_route(
    client: httpx.AsyncClient, token: str, name: str, zone: str, line: Any, duration: Any
) -> dict[str, Any]:
    captured = record("m04-route-candidates.json")
    route = captured if line is None else captured | {
        "route_id": f"test:{name}",
        "geometry": {"type": "LineString", "coordinates": [list(p) for p in line]},
        "duration_seconds": duration,
    }  # fmt: skip
    departure = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    samples = sample_route(
        GeoLineString.model_validate(route["geometry"]),
        departure_at=departure,
        duration_seconds=route["duration_seconds"],
        max_spacing_m=5000,
    )
    step = max(1, len(samples) // 40)
    chosen = samples[::step] + ([samples[-1]] if (len(samples) - 1) % step else [])
    lons = [s.longitude for s in samples]
    lats = [s.latitude for s in samples]
    query = {
        "samples": [
            {"longitude": s.longitude, "latitude": s.latitude, "eta": s.eta.isoformat(),
             "sample_id": f"{name}-{i}"}
            for i, s in enumerate(chosen)
        ],
        "include": ["WEATHER", "DISASTER"],
        "start": (departure - timedelta(days=2)).isoformat(),
        "end": (departure + timedelta(seconds=route["duration_seconds"])).isoformat(),
        "deadline_seconds": 60,
    }  # fmt: skip
    if max(lons) - min(lons) < 180:
        query["bbox"] = [min(lons) - 1, min(lats) - 1, max(lons) + 1, max(lats) + 1]
    async with httpx.AsyncClient(timeout=90) as module_04:
        answer = await module_04.post(
            f"{MODULE_04}/internal/v1/context/query",
            json=query,
            headers={"Authorization": f"Bearer {token}"},
        )
    answer.raise_for_status()
    data = answer.json()["data"]
    outcomes = {c["capability"]: c["outcome"] for c in data["capabilities"]}
    recommendation_at = datetime.now(UTC)

    settings = get_settings()
    engine = build_engine(settings.database_url)
    try:
        async with unit_of_work(build_session_factory(engine)) as session:
            repository = CanonicalRepository(session)
            stored = [await repository.ingest("disaster", e) for e in data["disaster_events"]]
            ids = await hazard_ids_in_corridor(
                session,
                samples,
                radius_m=settings.corridor_radius_m,
                start_at=departure,
                end_at=samples[-1].eta,
            )
            in_corridor = set(
                (await session.scalars(select(CanonicalRecord.source_id).where(
                    CanonicalRecord.id.in_(ids)))).all()
            )  # fmt: skip
    finally:
        await engine.dispose()
    corridor_events = [
        e for e in data["disaster_events"] if e["source"]["source_id"] in in_corridor
    ]

    weather = data["weather"] if outcomes.get("WEATHER") == "ANSWERED" else None
    disasters = corridor_events if outcomes.get("DISASTER") == "ANSWERED" else None
    qualities = {"route": route["quality"]}
    for key, capability, records in (
        ("weather", "WEATHER", data["weather"]),
        ("disaster", "DISASTER", data["disaster_events"]),
    ):
        derived = source_quality(outcomes.get(capability, "UNAVAILABLE"), records)
        if derived is not None:
            qualities[key] = derived
    body = {
        "request_id": str(uuid4()),
        "trip_id": str(uuid4()),
        "travel_window": {
            "starts_at": departure.isoformat(),
            "ends_at": samples[-1].eta.isoformat(),
            "timezone": zone,
        },
        "recommendation_at": recommendation_at.isoformat(),
        "route": route,
        "evidence": {"weather": weather, "disaster_events": disasters, "transport": []},
        "source_quality": qualities,
    }
    created = await client.post("/internal/v1/snapshots", json=body)
    snapshot = created.json().get("data", {})
    report = (
        await client.post(f"/internal/v1/snapshots/{snapshot['snapshot_id']}/validate")
    ).json()["data"] if created.status_code == 201 else {}  # fmt: skip
    return {
        "route": name,
        "timezone": zone,
        "module_04_outcomes": outcomes,
        "module_04_degraded": answer.json()["meta"].get("degraded_services", []),
        "weather_records": len(data["weather"]),
        "disaster_records_in_bbox": len(data["disaster_events"]),
        "disaster_records_stored": sum(1 for s in stored if s is not None),
        "disaster_records_in_corridor": len(corridor_events),
        "http_status": created.status_code,
        "snapshot_id": snapshot.get("snapshot_id"),
        "gate": report.get("gate"),
        "valid": report.get("valid"),
        "content_hash_matches": report.get("content_hash_matches"),
        "features": {
            k: snapshot.get("features", {}).get(k)
            for k in (
                "max_weather_severity_ordinal",
                "max_precipitation_probability",
                "max_wind_gust_kmh",
                "corridor_extreme_alert_active",
                "hazard_intersection_fraction",
                "critical_evidence_coverage",
            )
        },
        "local_departure": departure.astimezone(ZoneInfo(zone)).isoformat(),
    }


async def main_async(token: str) -> None:
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            for name, zone, line, duration in ROUTES:
                summary = await run_route(client, token, name, zone, line, duration)
                print(json.dumps(summary, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Live module 04 to snapshot run.")
    parser.add_argument("--database", default=f"m05_e2e_{uuid4().hex[:8]}")
    parser.add_argument("--keep", action="store_true", help="keep the database for restore")
    args = parser.parse_args()
    maintenance = os.environ["TEST_DATABASE_URL"]
    admin = create_engine(maintenance, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{args.database}"'))
    os.environ["POSTGRES_DB"] = args.database
    get_settings.cache_clear()
    token = get_settings().internal_service_token
    if token is None:
        raise SystemExit("INTERNAL_SERVICE_TOKEN is required")
    try:
        command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
        print(json.dumps({"database": args.database, "kept": args.keep,
                          "url": make_url(maintenance).set(database=args.database)
                          .render_as_string(hide_password=True)}))  # fmt: skip
        asyncio.run(main_async(token.get_secret_value()))
    finally:
        if not args.keep:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{args.database}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    main()
