"""Typed client for `data_integration.create_snapshot@1`
(`packages/contracts/openapi/internal-data-integration.yaml`).

Idempotency for this endpoint is body-based per its own spec ("Idempotent on `request_id` + SHA-256
of the canonical request body + schema version: a replay returns the stored snapshot with 200; the
same `request_id` with a different body returns 409") rather than an `Idempotency-Key` header, so
`create_snapshot` does not send one.
"""

from __future__ import annotations

from uuid import UUID

from app.settings import Settings
from app.tools.clients.base import ToolCallRecord, ToolClientBase
from app.tools.registry import REGISTRY
from app.tools.schemas import SnapshotCreateRequest, SnapshotResponse

_DESCRIPTOR = REGISTRY["data_integration.create_snapshot@1"]


class DataIntegrationClient(ToolClientBase):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            descriptor=_DESCRIPTOR,
            base_url=settings.data_integration_base_url,
            internal_service_token=(
                settings.internal_service_token.get_secret_value()
                if settings.internal_service_token is not None
                else None
            ),
            connect_timeout_seconds=settings.agent_tool_connect_timeout_seconds,
            total_timeout_seconds=settings.agent_tool_timeout_seconds,
            contract_version=settings.contract_version,
        )

    async def create_snapshot(
        self,
        request: SnapshotCreateRequest,
        *,
        correlation_id: UUID,
        traceparent: str,
    ) -> tuple[SnapshotResponse, ToolCallRecord]:
        return await self._post(
            "/internal/v1/snapshots",
            request,
            SnapshotResponse,
            request_id=request.request_id,
            correlation_id=correlation_id,
            traceparent=traceparent,
        )
