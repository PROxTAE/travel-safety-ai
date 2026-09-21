from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.settings import Settings

VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,99}$")


@dataclass(frozen=True)
class QdrantAliasStatus:
    reachable: bool
    collection_name: str | None
    detail: str | None


class QdrantManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        headers = {}
        if settings.qdrant_api_key:
            headers["api-key"] = settings.qdrant_api_key.get_secret_value()
        self.client = httpx.AsyncClient(
            base_url=settings.qdrant_url,
            headers=headers,
            timeout=settings.dependency_timeout_seconds,
        )

    async def close(self) -> None:
        await self.client.aclose()

    def collection_name(self, version: str) -> str:
        if not VERSION_RE.fullmatch(version):
            raise ValueError("Collection version contains unsupported characters")
        return f"{self.settings.qdrant_collection_prefix}-{version}"

    async def active_alias_status(self) -> QdrantAliasStatus:
        try:
            response = await self.client.get("/aliases")
            response.raise_for_status()
            aliases = response.json().get("result", {}).get("aliases", [])
            match = next(
                (
                    alias
                    for alias in aliases
                    if alias.get("alias_name") == self.settings.qdrant_active_alias
                ),
                None,
            )
            if match is None:
                return QdrantAliasStatus(True, None, "Active alias is not configured")
            return QdrantAliasStatus(True, str(match.get("collection_name")), None)
        except (httpx.HTTPError, ValueError, TypeError):
            return QdrantAliasStatus(False, None, "Qdrant health request failed")

    async def prepare_collection(self, *, version: str, vector_size: int) -> str:
        name = self.collection_name(version)
        response = await self.client.put(
            f"/collections/{name}",
            json={
                "vectors": {"size": vector_size, "distance": "Cosine"},
                "on_disk_payload": True,
            },
        )
        if response.status_code == 409:
            return name
        response.raise_for_status()
        return name

    async def activate_alias(self, *, collection_name: str) -> None:
        current = await self.active_alias_status()
        if not current.reachable:
            raise RuntimeError(current.detail or "Qdrant unavailable")
        actions: list[dict[str, Any]] = []
        if current.collection_name:
            actions.append({"delete_alias": {"alias_name": self.settings.qdrant_active_alias}})
        actions.append(
            {
                "create_alias": {
                    "collection_name": collection_name,
                    "alias_name": self.settings.qdrant_active_alias,
                }
            }
        )
        response = await self.client.post("/collections/aliases", json={"actions": actions})
        response.raise_for_status()

    async def upsert_points(
        self, *, collection_name: str, points: list[dict[str, Any]], wait: bool = True
    ) -> None:
        response = await self.client.put(
            f"/collections/{collection_name}/points",
            params={"wait": str(wait).lower()},
            json={"points": points},
        )
        response.raise_for_status()

    async def search(
        self,
        *,
        vector: list[float],
        region: str | None,
        language: str | None,
        hazard: str | None,
        at: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        status = await self.active_alias_status()
        if not status.reachable or not status.collection_name:
            raise RuntimeError(status.detail or "NO_ACTIVE_KNOWLEDGE_COLLECTION")
        must: list[dict[str, Any]] = [
            {"key": "effective_at_epoch", "range": {"lte": at.timestamp()}},
            {"key": "expires_at_epoch", "range": {"gte": at.timestamp()}},
        ]
        for key, value in (("regions", region), ("language", language), ("hazards", hazard)):
            if value:
                must.append({"key": key, "match": {"value": value}})
        response = await self.client.post(
            f"/collections/{status.collection_name}/points/search",
            json={
                "vector": vector,
                "filter": {"must": must},
                "limit": limit,
                "with_payload": True,
                "score_threshold": 0.25,
            },
        )
        response.raise_for_status()
        result = response.json().get("result", [])
        return [
            {**dict(item.get("payload", {})), "retrieval_score": float(item.get("score", 0))}
            for item in result
            if isinstance(item, dict)
        ]

    async def rollback_alias(self, *, previous_collection_name: str) -> None:
        if not previous_collection_name.startswith(f"{self.settings.qdrant_collection_prefix}-"):
            raise ValueError("Rollback collection is outside the managed prefix")
        await self.activate_alias(collection_name=previous_collection_name)
