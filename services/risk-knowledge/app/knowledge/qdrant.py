from __future__ import annotations

import re
from dataclasses import dataclass
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
