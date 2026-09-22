"""Shared async HTTP client base for typed tool clients.

Implements the parts of the plan's "Tool registry rules" that apply uniformly to every tool
client: required headers, connect/read/total timeout, retry limited to the tool's own declared
retryable codes, response-schema validation, and safe error mapping (a `ToolCallError` always
carries one of the contract's stable error codes — 00_API_AND_DATA_CONTRACTS.md §1 — never a raw
exception message or provider response body). A concrete client
(`app/tools/clients/data_integration.py`, `risk_knowledge.py`) supplies only its own request/
response models and `ToolDescriptor`.

Cancellation: this class does no cooperative-cancellation bookkeeping of its own — an
`asyncio.CancelledError` raised into an in-flight `httpx` call propagates through `AsyncRetrying`
and out of `_post` normally, the same way any other exception in an `async def` does. There is
nothing extra to wire up.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.tools.registry import ToolDescriptor
from app.tools.schemas import ToolErrorEnvelope

ResponseT = TypeVar("ResponseT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """What `agent.tool_calls` stores (00_API_AND_DATA_CONTRACTS.md §8: "ห้ามเก็บ secret/raw
    sensitive payload") — a hash of the request body, never the body itself, and no response body
    at all."""

    tool_name: str
    input_hash: str
    status: str  # "success" | "failed"
    duration_ms: int
    error_code: str | None


class ToolCallError(RuntimeError):
    """Raised by a tool client on any failure: network, timeout, non-2xx, or a response that
    fails schema validation. `record` is always populated — callers persist it to
    `agent.tool_calls` on the failure path the same way they would on success.
    """

    def __init__(
        self, error_code: str, retryable: bool, message: str, record: ToolCallRecord | None = None
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        self.record = record


def _hash_request(payload: BaseModel) -> str:
    body = payload.model_dump_json().encode("utf-8")
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


class ToolClientBase:
    def __init__(
        self,
        descriptor: ToolDescriptor,
        base_url: str,
        internal_service_token: str | None,
        connect_timeout_seconds: float,
        total_timeout_seconds: float,
        contract_version: str = "1.0.0",
    ) -> None:
        self._descriptor = descriptor
        self._token = internal_service_token
        self._contract_version = contract_version
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=total_timeout_seconds,
                write=total_timeout_seconds,
                pool=total_timeout_seconds,
            ),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ToolClientBase:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _headers(
        self, request_id: UUID, correlation_id: UUID, traceparent: str, idempotency_key: str | None
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": str(request_id),
            "X-Correlation-ID": str(correlation_id),
            "traceparent": traceparent,
            "X-Contract-Version": self._contract_version,
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._descriptor.idempotent and idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _parse_error_code(self, response: httpx.Response) -> str:
        try:
            envelope = ToolErrorEnvelope.model_validate_json(response.content)
        except Exception:
            return "INTERNAL_ERROR"
        return envelope.error.code

    def _should_retry(self, exc: BaseException) -> bool:
        if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
            return True
        return isinstance(exc, ToolCallError) and exc.retryable

    async def _post(
        self,
        path: str,
        payload: BaseModel,
        response_model: type[ResponseT],
        *,
        request_id: UUID,
        correlation_id: UUID,
        traceparent: str,
        idempotency_key: str | None = None,
    ) -> tuple[ResponseT, ToolCallRecord]:
        headers = self._headers(request_id, correlation_id, traceparent, idempotency_key)
        body = payload.model_dump_json()
        input_hash = _hash_request(payload)
        started = time.monotonic()

        async def attempt() -> ResponseT:
            try:
                response = await self._client.post(path, content=body, headers=headers)
            except httpx.TimeoutException as exc:
                raise ToolCallError("DEPENDENCY_TIMEOUT", True, "the dependency timed out") from exc
            except httpx.HTTPError as exc:
                raise ToolCallError(
                    "DEPENDENCY_UNAVAILABLE", True, "the dependency is unreachable"
                ) from exc

            if response.status_code >= 400:
                error_code = self._parse_error_code(response)
                retryable = error_code in self._descriptor.retryable_error_codes
                raise ToolCallError(
                    error_code,
                    retryable,
                    f"{self._descriptor.name} returned HTTP {response.status_code}",
                )

            try:
                return response_model.model_validate_json(response.content)
            except Exception as exc:
                raise ToolCallError(
                    "INTERNAL_ERROR", False, "response failed schema validation"
                ) from exc

        retrying: AsyncRetrying = AsyncRetrying(
            stop=stop_after_attempt(self._descriptor.max_attempts),
            wait=wait_exponential_jitter(initial=0.2, max=2.0),
            retry=retry_if_exception(self._should_retry),
            reraise=True,
        )

        try:
            parsed: ResponseT = await retrying(attempt)
        except ToolCallError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            record = ToolCallRecord(
                self._descriptor.name, input_hash, "failed", duration_ms, exc.error_code
            )
            raise ToolCallError(exc.error_code, exc.retryable, str(exc), record) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        record = ToolCallRecord(self._descriptor.name, input_hash, "success", duration_ms, None)
        return parsed, record
