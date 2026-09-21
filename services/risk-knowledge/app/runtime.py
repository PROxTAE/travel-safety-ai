from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from app.contracts import ModelReference
from app.db import Database
from app.integrations.snapshots import SnapshotClient
from app.knowledge.qdrant import QdrantManager
from app.metrics import DEPENDENCY_STATUS
from app.repositories.registry import (
    ActiveCollection,
    ActiveModel,
    get_active_collection,
    get_active_model,
)
from app.risk.artifact_loader import ArtifactUnavailable, ArtifactVerifier
from app.risk.inference import RiskPredictor
from app.settings import Settings
from app.timeouts import hard_timeout


@dataclass
class ModelRuntimeStatus:
    status: str = "WARMING"
    reason: str | None = None
    model: ModelReference | None = None


@dataclass
class KnowledgeRuntimeStatus:
    status: str = "WARMING"
    reason: str | None = None
    collection_version: str | None = None
    document_cutoff: datetime | None = None


class RuntimeState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings)
        self.qdrant = QdrantManager(settings)
        self.artifacts = ArtifactVerifier(settings)
        self.snapshots = SnapshotClient(settings)
        self.model = ModelRuntimeStatus()
        self.predictor: RiskPredictor | None = None
        self.knowledge = KnowledgeRuntimeStatus()

    async def warmup(self) -> None:
        await self.refresh_model()
        await self.refresh_knowledge()

    async def close(self) -> None:
        await self.qdrant.close()
        await self.snapshots.close()
        await self.database.dispose()

    async def _active_model_record(self) -> ActiveModel | None:
        if self.database.sessions is None:
            return None
        async with self.database.sessions() as session:
            return await get_active_model(session, self.settings.active_model_name)

    async def _active_collection_record(self) -> ActiveCollection | None:
        if self.database.sessions is None:
            return None
        async with self.database.sessions() as session:
            return await get_active_collection(session)

    async def refresh_model(self) -> ModelRuntimeStatus:
        if self.database.sessions is None:
            self.model = ModelRuntimeStatus("UNAVAILABLE", "DATABASE_UNAVAILABLE", None)
            return self.model
        try:
            record = await hard_timeout(
                self._active_model_record(), self.settings.dependency_timeout_seconds
            )
            if record is None:
                self.model = ModelRuntimeStatus("UNAVAILABLE", "NO_APPROVED_ACTIVE_MODEL", None)
                return self.model
            async with asyncio.timeout(self.settings.artifact_verification_timeout_seconds):
                artifact = await asyncio.to_thread(self.artifacts.verify, record)
            reference = ModelReference(
                name=record.name,
                version=record.version,
                feature_schema_version="1.0.0",
                artifact_checksum=artifact.checksum,
            )
            self.model = ModelRuntimeStatus(
                status="AVAILABLE",
                reason=None,
                model=reference,
            )
            self.predictor = await asyncio.to_thread(RiskPredictor, artifact.path, reference)
        except TimeoutError:
            self.predictor = None
            self.model = ModelRuntimeStatus("UNAVAILABLE", "MODEL_WARMUP_TIMEOUT", None)
        except ArtifactUnavailable as exc:
            self.predictor = None
            self.model = ModelRuntimeStatus("UNAVAILABLE", exc.reason, None)
        except Exception:
            self.predictor = None
            self.model = ModelRuntimeStatus("UNAVAILABLE", "MODEL_REGISTRY_UNAVAILABLE", None)
        return self.model

    async def refresh_knowledge(self) -> KnowledgeRuntimeStatus:
        alias = await self.qdrant.active_alias_status()
        if not alias.reachable:
            DEPENDENCY_STATUS.labels("qdrant").set(0)
            self.knowledge = KnowledgeRuntimeStatus("UNAVAILABLE", alias.detail, None, None)
            return self.knowledge
        DEPENDENCY_STATUS.labels("qdrant").set(1)
        if not alias.collection_name:
            self.knowledge = KnowledgeRuntimeStatus(
                "UNAVAILABLE", "NO_ACTIVE_KNOWLEDGE_COLLECTION", None, None
            )
            return self.knowledge
        if self.database.sessions is None:
            self.knowledge = KnowledgeRuntimeStatus(
                "UNAVAILABLE", "DATABASE_UNAVAILABLE", None, None
            )
            return self.knowledge
        try:
            record = await hard_timeout(
                self._active_collection_record(), self.settings.dependency_timeout_seconds
            )
            if record is None or record.collection_name != alias.collection_name:
                self.knowledge = KnowledgeRuntimeStatus(
                    "UNAVAILABLE", "QDRANT_DATABASE_ALIAS_MISMATCH", None, None
                )
                return self.knowledge
            if not record.approved_by or not record.approved_at or not record.evaluation_checksum:
                self.knowledge = KnowledgeRuntimeStatus(
                    "UNAVAILABLE", "KNOWLEDGE_COLLECTION_NOT_APPROVED", None, None
                )
                return self.knowledge
            self.knowledge = KnowledgeRuntimeStatus(
                "AVAILABLE", None, record.version, record.document_cutoff
            )
        except TimeoutError:
            self.knowledge = KnowledgeRuntimeStatus(
                "UNAVAILABLE", "KNOWLEDGE_REGISTRY_TIMEOUT", None, None
            )
        except Exception:
            self.knowledge = KnowledgeRuntimeStatus(
                "UNAVAILABLE", "KNOWLEDGE_REGISTRY_UNAVAILABLE", None, None
            )
        return self.knowledge
