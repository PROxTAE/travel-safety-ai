"""Volume data for spatial performance checks; test-only, never read at runtime.

Every seeded row reuses the payload of the captured module 04 USGS event
(tests/fixtures/m04-usgs-event.json, HTTP 200). Only the position, id and time
are varied on a deterministic grid over Thailand, so the volume is synthetic
while the record shape is real. Rows use the `load:` source prefix.
"""

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FIXTURE = Path(__file__).parent / "fixtures" / "m04-usgs-event.json"
WINDOW_START = datetime(2026, 9, 17, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 17, 10, tzinfo=UTC)
# Test-only route between the Bangkok and Chiang Mai landmark coordinates of the Phase 0 captures.
ROUTE = [(100.5018, 13.7563), (100.1372, 15.7047), (99.495, 18.2888), (98.9853, 18.7883)]


async def seed_disasters(session: AsyncSession, count: int) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["records"][0]
    side = math.ceil(math.sqrt(count))
    await session.execute(
        text("""
        INSERT INTO integration.canonical_records (
            id, record_type, source_id, content_hash, schema_version, transform_version,
            payload_json, lineage_json, geometry, valid_at, fetched_at
        )
        SELECT
            gen_random_uuid(), 'disaster', 'load:' || g,
            'sha256:' || lpad(to_hex(g), 64, '0'), '1.0.0', 'load',
            CAST(:payload AS jsonb), '{}'::jsonb,
            ST_SetSRID(
                ST_MakePoint(
                    97.0 + (g % :side) * CAST(:lon_step AS double precision),
                    5.5 + (g / :side) * CAST(:lat_step AS double precision)
                ),
                4326
            ),
            CAST(:window_start AS timestamptz) - (g % 96) * interval '1 hour',
            CAST(:window_start AS timestamptz)
        FROM generate_series(1, :count) AS g
        ON CONFLICT ON CONSTRAINT uq_canonical_version DO NOTHING
    """),
        {
            "payload": json.dumps(payload),
            "window_start": WINDOW_START,
            "count": count,
            # A square grid over 97-104E, 5.5-21.5N whatever the row count.
            "side": side,
            "lon_step": 7.0 / side,
            "lat_step": 16.0 / side,
        },
    )
    await session.execute(text("ANALYZE integration.canonical_records"))


async def remove_seed(session: AsyncSession) -> None:
    await session.execute(
        text("DELETE FROM integration.canonical_records WHERE source_id LIKE 'load:%'")
    )
