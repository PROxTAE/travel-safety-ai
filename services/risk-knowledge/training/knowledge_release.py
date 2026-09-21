"""Build and safely release a versioned knowledge collection from approved real sources."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from app.db import Database
from app.knowledge.pipeline import chunk_pdf, download_approved_source, qdrant_points
from app.knowledge.qdrant import QdrantManager
from app.repositories.registry import get_approved_collection, mark_collection_active
from app.settings import Settings


def load_source_manifest(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, list) or not sources:
        raise ValueError("knowledge source manifest must contain sources")
    return [dict(source) for source in sources]


async def build_and_release(
    *,
    settings: Settings,
    version: str,
    manifest_path: Path,
    evaluation_path: Path,
    activate: bool,
) -> dict[str, object]:
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    if not evaluation.get("passed", False):
        raise ValueError("KNOWLEDGE_EVALUATION_NOT_PASSED")
    sources = load_source_manifest(manifest_path)
    allowed_hosts = {
        str(source["source_url"]).split("/", 3)[2]
        for source in sources
        if str(source.get("source_url", "")).startswith("https://")
    }
    chunks = []
    for source in sources:
        content = await download_approved_source(source, allowed_hosts)
        chunks.extend(chunk_pdf(content, source))
    qdrant = QdrantManager(settings)
    database = Database(settings)
    previous_collection: str | None = None
    try:
        collection = await qdrant.prepare_collection(
            version=version, vector_size=settings.qdrant_vector_size
        )
        await qdrant.upsert_points(
            collection_name=collection,
            points=qdrant_points(chunks, dimensions=settings.qdrant_vector_size),
        )
        if activate:
            if database.sessions is None:
                raise ValueError("DATABASE_REQUIRED_FOR_COLLECTION_ACTIVATION")
            async with database.sessions() as session:
                approved = await get_approved_collection(session, version)
                if approved is None or approved.collection_name != collection:
                    raise ValueError("COLLECTION_MUST_BE_APPROVED_BEFORE_ACTIVATION")
                current = await qdrant.active_alias_status()
                previous_collection = current.collection_name
                await qdrant.activate_alias(collection_name=collection)
                try:
                    await mark_collection_active(session, approved.id)
                except Exception:
                    if previous_collection:
                        await qdrant.rollback_alias(previous_collection_name=previous_collection)
                    raise
        manifest_checksum = "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        return {
            "version": version,
            "collection": collection,
            "documents": len(sources),
            "chunks": len(chunks),
            "manifest_checksum": manifest_checksum,
            "evaluation_checksum": "sha256:"
            + hashlib.sha256(evaluation_path.read_bytes()).hexdigest(),
            "active": activate,
            "previous_collection": previous_collection,
        }
    finally:
        await qdrant.close()
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        build_and_release(
            settings=Settings(),
            version=args.version,
            manifest_path=args.manifest,
            evaluation_path=args.evaluation,
            activate=args.activate,
        )
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
