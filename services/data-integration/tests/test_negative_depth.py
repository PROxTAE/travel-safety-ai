"""Issue #75: USGS reports negative hypocentre depths, which the contract now allows.

The record is the captured module 04 USGS event with its depth set to -0.74 km,
the value USGS published for ci41335751 (California) on 2026-09-21.
"""

import json
from pathlib import Path

from app.cli.operations import backfill
from app.repositories.db import build_engine

FIXTURE = Path(__file__).parent / "fixtures" / "m04-usgs-event.json"


def usgs(depth_km: float, source_id: str) -> str:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["records"][0]
    return json.dumps(
        raw | {"depth_km": depth_km, "source": raw["source"] | {"source_id": source_id}}
    )


async def test_negative_depth_is_stored_not_quarantined(isolated_database: str) -> None:
    engine = build_engine(isolated_database)
    try:
        report = await backfill(engine, "disaster", [usgs(-0.74, "usgs:depth-above-sea-level")])
        assert (report.stored, report.quarantined) == (1, 0)
    finally:
        await engine.dispose()


async def test_depth_below_contract_bound_is_still_quarantined(isolated_database: str) -> None:
    engine = build_engine(isolated_database)
    try:
        report = await backfill(engine, "disaster", [usgs(-16.0, "usgs:depth-below-bound")])
        assert (report.stored, report.quarantined) == (0, 1)
    finally:
        await engine.dispose()
