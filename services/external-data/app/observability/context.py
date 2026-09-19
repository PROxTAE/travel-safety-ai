"""Per-request correlation identifiers, propagated to logs, metrics and traces."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"
CONTRACT_VERSION_HEADER = "X-Contract-Version"


def new_id() -> str:
    return str(uuid.uuid4())


def current_ids() -> dict[str, str]:
    return {
        "request_id": request_id_var.get(),
        "correlation_id": correlation_id_var.get(),
    }
