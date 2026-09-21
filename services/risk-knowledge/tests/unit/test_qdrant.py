from __future__ import annotations

import httpx
import pytest
import respx

from app.knowledge.qdrant import QdrantManager
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        QDRANT_URL="http://qdrant.test",
        QDRANT_API_KEY="test-only-qdrant-key",
        RISK_KNOWLEDGE_DEPENDENCY_TIMEOUT_SECONDS=1,
    )


@pytest.mark.asyncio
@respx.mock
async def test_alias_status_reports_missing_alias_without_faking_availability() -> None:
    respx.get("http://qdrant.test/aliases").mock(
        return_value=httpx.Response(200, json={"result": {"aliases": []}})
    )
    manager = QdrantManager(_settings())
    try:
        status = await manager.active_alias_status()
    finally:
        await manager.close()
    assert status.reachable is True
    assert status.collection_name is None
    assert status.detail == "Active alias is not configured"


@pytest.mark.asyncio
@respx.mock
async def test_alias_status_resolves_configured_collection() -> None:
    respx.get("http://qdrant.test/aliases").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "aliases": [
                        {
                            "alias_name": "sta-knowledge-active",
                            "collection_name": "sta-knowledge-1.0.0",
                        }
                    ]
                }
            },
        )
    )
    manager = QdrantManager(_settings())
    try:
        status = await manager.active_alias_status()
    finally:
        await manager.close()
    assert status.collection_name == "sta-knowledge-1.0.0"
    assert status.detail is None


@pytest.mark.asyncio
@respx.mock
async def test_qdrant_http_error_is_unavailable() -> None:
    respx.get("http://qdrant.test/aliases").mock(return_value=httpx.Response(503))
    manager = QdrantManager(_settings())
    try:
        status = await manager.active_alias_status()
    finally:
        await manager.close()
    assert status.reachable is False
    assert status.detail == "Qdrant health request failed"


@pytest.mark.asyncio
@respx.mock
async def test_prepare_and_activate_collection_lifecycle() -> None:
    prepare = respx.put("http://qdrant.test/collections/sta-knowledge-1.0.0").mock(
        return_value=httpx.Response(200, json={"result": True})
    )
    aliases = respx.get("http://qdrant.test/aliases").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "aliases": [
                        {
                            "alias_name": "sta-knowledge-active",
                            "collection_name": "sta-knowledge-0.9.0",
                        }
                    ]
                }
            },
        )
    )
    activate = respx.post("http://qdrant.test/collections/aliases").mock(
        return_value=httpx.Response(200, json={"result": True})
    )
    manager = QdrantManager(_settings())
    try:
        name = await manager.prepare_collection(version="1.0.0", vector_size=768)
        await manager.activate_alias(collection_name=name)
    finally:
        await manager.close()
    assert name == "sta-knowledge-1.0.0"
    assert prepare.called and aliases.called and activate.called
    actions = activate.calls.last.request.read()
    assert b"delete_alias" in actions
    assert b"create_alias" in actions


def test_collection_version_rejects_unsafe_characters() -> None:
    manager = QdrantManager(_settings())
    with pytest.raises(ValueError, match="unsupported characters"):
        manager.collection_name("../../escape")
