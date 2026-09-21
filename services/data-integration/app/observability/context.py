"""Request and correlation identifiers."""

from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="")
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
