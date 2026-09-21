from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest

from app.integrations.snapshots import SnapshotClient, SnapshotUnavailable
from app.settings import Settings


@pytest.mark.asyncio
async def test_snapshot_client_accepts_exact_immutable_snapshot(
    snapshot_payload: dict[str, Any],
) -> None:
    snapshot_id = UUID(snapshot_payload["snapshot_id"])

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(str(snapshot_id))
        return httpx.Response(200, json={"data": snapshot_payload, "meta": {}})

    client = SnapshotClient(Settings(DATA_INTEGRATION_URL="https://m05.internal"))
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://m05.internal", transport=httpx.MockTransport(handler)
    )
    snapshot = await client.get(snapshot_id)
    assert snapshot.snapshot_id == snapshot_id
    await client.close()


@pytest.mark.asyncio
async def test_snapshot_client_rejects_mismatched_snapshot(
    snapshot_payload: dict[str, Any],
) -> None:
    requested = UUID("90000000-0000-4000-8000-000000000001")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": snapshot_payload, "meta": {}})

    client = SnapshotClient(Settings(DATA_INTEGRATION_URL="https://m05.internal"))
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://m05.internal", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(SnapshotUnavailable, match="SNAPSHOT_ID_MISMATCH"):
        await client.get(requested)
    await client.close()
