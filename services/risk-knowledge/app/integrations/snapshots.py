from __future__ import annotations

from uuid import UUID

import httpx

from app.contracts import IntegratedTravelContext
from app.settings import Settings


class SnapshotUnavailable(RuntimeError):
    pass


class SnapshotClient:
    """Read immutable M05 snapshots; never reconstruct provider data locally."""

    def __init__(self, settings: Settings) -> None:
        headers = {"X-Contract-Version": "1"}
        if settings.data_integration_token:
            headers["Authorization"] = (
                f"Bearer {settings.data_integration_token.get_secret_value()}"
            )
        self.client = httpx.AsyncClient(
            base_url=settings.data_integration_url,
            headers=headers,
            timeout=settings.dependency_timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def get(self, snapshot_id: UUID) -> IntegratedTravelContext:
        try:
            response = await self.client.get(f"/internal/v1/snapshots/{snapshot_id}")
            response.raise_for_status()
            payload = response.json()
            snapshot = IntegratedTravelContext.model_validate(payload["data"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise SnapshotUnavailable("IMMUTABLE_SNAPSHOT_UNAVAILABLE") from exc
        if snapshot.snapshot_id != snapshot_id:
            raise SnapshotUnavailable("SNAPSHOT_ID_MISMATCH")
        return snapshot
