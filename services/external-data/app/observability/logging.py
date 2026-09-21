"""Structured JSON logging with redaction.

Field set is fixed by 00_SHARED_PROJECT_CONTEXT.md § 12. Redaction is not a
nice-to-have: § 11 requires tokens, email, phone, medical notes and exact
coordinates to be stripped before a line is written.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.observability.context import correlation_id_var, request_id_var

# Redaction happens on the rendered value, so it also catches secrets that
# arrive inside an exception message or a provider URL.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?i)(api[_-]?key|apikey|token|secret|password|authorization)=[^&\s\"']+"),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"(?<![\d.])\+?\d[\d\s-]{7,}\d(?![\d.])"), "[PHONE]"),
]

# Exact coordinates identify a person. Logs keep ~11 km precision; the full
# value stays in the response payload, which is access-controlled.
_COORD_KEYS = {"latitude", "longitude", "lat", "lon", "lng"}
_COORD_PRECISION = 1

# An ISO-8601 timestamp looks exactly like a phone number to the pattern above:
# "2026-09-19" is ten digits joined by dashes. Timestamps are the field we log
# most often, so they are lifted out before redaction runs and restored after.
_ISO_DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}" r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)
# Same trap, same shape: a uuid4 is runs of hex digits joined by dashes, so the
# phone pattern eats roughly one in four of them — and those are exactly the
# request_id and correlation_id values the observability contract depends on.
_UUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")

_PLACEHOLDER = "\x00keep{}\x00"


def _redact_text(value: str) -> str:
    preserved: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        preserved.append(match.group(0))
        return _PLACEHOLDER.format(len(preserved) - 1)

    value = _ISO_DATETIME.sub(_stash, value)
    value = _UUID.sub(_stash, value)
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    for index, original in enumerate(preserved):
        value = value.replace(_PLACEHOLDER.format(index), original)
    return value


def _redact(_: Any, __: str, event_dict: EventDict) -> EventDict:
    for key, value in list(event_dict.items()):
        if key in _COORD_KEYS and isinstance(value, int | float):
            event_dict[key] = round(float(value), _COORD_PRECISION)
        elif isinstance(value, str):
            event_dict[key] = _redact_text(value)
    return event_dict


def _add_context(_: Any, __: str, event_dict: EventDict) -> EventDict:
    event_dict.setdefault("request_id", request_id_var.get())
    event_dict.setdefault("correlation_id", correlation_id_var.get())
    span = structlog.contextvars.get_contextvars().get("trace_id")
    if span:
        event_dict.setdefault("trace_id", span)
    return event_dict


def configure_logging(*, service: str, environment: str, level: str) -> None:
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        _add_context,
        _redact,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level, logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service, environment=environment)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    for noisy in ("uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True


def get_logger(name: str = "external-data") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
