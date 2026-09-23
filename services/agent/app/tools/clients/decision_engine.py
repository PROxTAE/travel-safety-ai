"""Typed client for `decision_engine.create_decision@1`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.settings import Settings
from app.tools.clients.base import ToolCallRecord, ToolClientBase
from app.tools.registry import REGISTRY

_DESCRIPTOR = REGISTRY["decision_engine.create_decision@1"]


class DecisionEngineClient(ToolClientBase):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            descriptor=_DESCRIPTOR,
            base_url=settings.decision_engine_base_url,
            internal_service_token=(
                settings.internal_service_token.get_secret_value()
                if settings.internal_service_token is not None
                else None
            ),
            connect_timeout_seconds=settings.agent_tool_connect_timeout_seconds,
            total_timeout_seconds=settings.agent_tool_timeout_seconds,
            contract_version=settings.contract_version,
        )

    async def create_decision(
        self,
        payload: dict[str, Any] | BaseModel,
        *,
        request_id: UUID,
        correlation_id: UUID,
        traceparent: str,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], ToolCallRecord]:
        return await self._post(
            "/internal/v1/decisions",
            payload,
            dict,
            request_id=request_id,
            correlation_id=correlation_id,
            traceparent=traceparent,
            idempotency_key=idempotency_key or str(request_id),
        )
