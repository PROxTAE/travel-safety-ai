"""Typed client for `risk_knowledge.build_evidence_package@1`
(`packages/contracts/openapi/internal-risk-knowledge.yaml`).

Unlike data-integration, this endpoint's `X-Request-ID` is a required header, not a body field
(`EvidencePackageRequest` has no `request_id` of its own) — `build_evidence_package` takes
`request_id` as an explicit parameter rather than reading it off the payload.
"""

from __future__ import annotations

from uuid import UUID

from app.settings import Settings
from app.tools.clients.base import ToolCallRecord, ToolClientBase
from app.tools.registry import REGISTRY
from app.tools.schemas import EvidencePackageRequest, EvidencePackageResponse

_DESCRIPTOR = REGISTRY["risk_knowledge.build_evidence_package@1"]


class RiskKnowledgeClient(ToolClientBase):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            descriptor=_DESCRIPTOR,
            base_url=settings.risk_knowledge_base_url,
            internal_service_token=(
                settings.internal_service_token.get_secret_value()
                if settings.internal_service_token is not None
                else None
            ),
            connect_timeout_seconds=settings.agent_tool_connect_timeout_seconds,
            total_timeout_seconds=settings.agent_tool_timeout_seconds,
            contract_version=settings.contract_version,
        )

    async def build_evidence_package(
        self,
        request: EvidencePackageRequest,
        *,
        request_id: UUID,
        correlation_id: UUID,
        traceparent: str,
    ) -> tuple[EvidencePackageResponse, ToolCallRecord]:
        return await self._post(
            "/internal/v1/evidence/package",
            request,
            EvidencePackageResponse,
            request_id=request_id,
            correlation_id=correlation_id,
            traceparent=traceparent,
        )
