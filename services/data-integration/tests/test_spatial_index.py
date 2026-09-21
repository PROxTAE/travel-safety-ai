"""The served corridor query uses the geography GiST index at volume.

Rows come from tests/load_seed.py (captured USGS payload on a synthetic grid).
"""

import json

from load_seed import ROUTE, WINDOW_END, WINDOW_START, remove_seed, seed_disasters
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.canonical import GeoLineString
from app.pipeline.corridor import sample_route
from app.pipeline.spatial import HAZARD_QUERY, corridor_geojson, hazard_ids_in_corridor


def _index_names(plan: object) -> set[str]:
    if isinstance(plan, dict):
        found = {plan["Index Name"]} if "Index Name" in plan else set()
        return found.union(*(_index_names(value) for value in plan.values()))
    if isinstance(plan, list):
        return set().union(*(_index_names(item) for item in plan))
    return set()


async def test_corridor_query_uses_geography_index(isolated_database: str) -> None:
    engine = create_async_engine(isolated_database)
    samples = sample_route(
        GeoLineString(type="LineString", coordinates=ROUTE),
        departure_at=WINDOW_START,
        duration_seconds=(WINDOW_END - WINDOW_START).total_seconds(),
        max_spacing_m=5000,
    )
    params = {
        "route": corridor_geojson(samples),
        "radius_m": 5000,
        "start_at": WINDOW_START,
        "end_at": WINDOW_END,
    }
    try:
        async with AsyncSession(engine) as session:
            await seed_disasters(session, 5000)
            await session.commit()
            plan = (
                await session.execute(text("EXPLAIN (FORMAT JSON) " + HAZARD_QUERY), params)
            ).scalar_one()
            plan = json.loads(plan) if isinstance(plan, str) else plan
            assert "ix_canonical_geography" in _index_names(plan)
            found = await hazard_ids_in_corridor(
                session, samples, radius_m=5000, start_at=WINDOW_START, end_at=WINDOW_END
            )
            # The grid is dense enough that the corridor must hit some rows, but far from all.
            assert 0 < len(found) < 5000
    finally:
        async with AsyncSession(engine) as session:
            await remove_seed(session)
            await session.commit()
        await engine.dispose()
