from __future__ import annotations

import argparse
import asyncio
import json

from app.db import Database
from app.knowledge.qdrant import QdrantManager
from app.repositories.registry import (
    get_approved_collection,
    mark_collection_active,
    register_draft_collection,
)
from app.settings import get_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage versioned Qdrant knowledge collections")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="Create a DRAFT collection without an alias")
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--vector-size", type=int)
    activate = subparsers.add_parser("activate", help="Switch the alias to an APPROVED collection")
    activate.add_argument("--version", required=True)
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings)
    qdrant = QdrantManager(settings)
    try:
        if database.sessions is None:
            raise RuntimeError(database.configuration_error or "Database unavailable")
        if args.command == "prepare":
            vector_size = args.vector_size or settings.qdrant_vector_size
            collection_name = await qdrant.prepare_collection(
                version=args.version, vector_size=vector_size
            )
            async with database.sessions() as session:
                draft_record = await register_draft_collection(
                    session,
                    version=args.version,
                    collection_name=collection_name,
                    vector_size=vector_size,
                )
            print(
                json.dumps(
                    {
                        "status": "DRAFT",
                        "version": draft_record.version,
                        "collection_name": draft_record.collection_name,
                        "alias_changed": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        async with database.sessions() as session:
            approved_record = await get_approved_collection(session, args.version)
        if approved_record is None:
            raise RuntimeError("Collection must be APPROVED in PostgreSQL before activation")
        if (
            not approved_record.evaluation_checksum
            or not approved_record.manifest_checksum
            or not approved_record.approved_by
        ):
            raise RuntimeError("Approved collection metadata is incomplete")
        await qdrant.activate_alias(collection_name=approved_record.collection_name)
        async with database.sessions() as session:
            await mark_collection_active(session, approved_record.id)
        print(
            json.dumps(
                {
                    "status": "ACTIVE",
                    "version": approved_record.version,
                    "collection_name": approved_record.collection_name,
                    "alias_changed": True,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        await qdrant.close()
        await database.dispose()


def main() -> None:
    args = _parser().parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
