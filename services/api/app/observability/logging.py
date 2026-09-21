"""Structured JSON logging with redaction built into the pipeline.

Two things are deliberate here.

**The log line is JSON with a fixed set of fields.** `request_id`, `correlation_id` and `trace_id`
are on every line, so one request can be followed across eight services without anyone having to
grep for a substring.

**Redaction is a processor, not a convention.** Asking developers to remember not to log a token
fails eventually; every log this service emits passes through `redact_processor` instead. It
removes credentials, contact details and exact coordinates wherever they appear, however deeply
nested. A latitude in a log file is a person's location history, and the privacy rules treat it
the same as a medical note.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.types import EventDict, Processor

#: Keys whose value is replaced wholesale. Matching is case-insensitive and on the whole key, so
#: `authorization` is caught but `authorization_policy_version` is not.
REDACTED_KEYS: frozenset[str] = frozenset(
    {
        # Credentials
        "authorization",
        "access_token",
        "id_token",
        "refresh_token",
        "token",
        "jwt",
        "password",
        "secret",
        "client_secret",
        "api_key",
        "apikey",
        "cookie",
        "set-cookie",
        "session",
        "idempotency-key",
        "idempotency_key",
        # Direct identifiers
        "email",
        "phone",
        "phone_number",
        "display_name",
        "given_name",
        "family_name",
        # Health data
        "medical_notes",
        "allergies",
        "medications",
        "blood_type",
        "emergency_profile",
        "encrypted_payload",
        "contacts",
        "insurance",
        "policy_reference",
        # Precise location. Coarse `country_code` and `timezone` stay: they are what make a log
        # useful for debugging coverage without describing where a person was.
        "lat",
        "lon",
        "latitude",
        "longitude",
        "coordinates",
        "origin",
        "destination",
        "location",
        "geometry",
        "bbox",
    }
)

#: Whole-payload keys that are never logged at any depth, because there is no safe subset.
DROPPED_KEYS: frozenset[str] = frozenset({"body", "request_body", "response_body", "payload"})

#: Keys whose value is a system-generated identifier, never user data. They skip the text
#: scrubbers: a UUID whose first group happens to be eight digits would otherwise be mangled by the
#: long-number rule, and a correlation id that changes shape between two log lines is worse than
#: useless — it is the one field that has to survive verbatim across eight services.
SAFE_IDENTIFIER_KEYS: frozenset[str] = frozenset(
    {
        "request_id",
        "correlation_id",
        "trace_id",
        "span_id",
        "source_id",
        "trip_id",
        "conversation_id",
        "recommendation_id",
        "decision_id",
        "snapshot_id",
        "user_id",
        "event_id",
        "route_id",
        "assessment_id",
        "subscription_id",
        "feedback_id",
        "timestamp",
        "duration_ms",
    }
)

REDACTED = "[redacted]"

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")
_EMAIL = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_LONG_DIGITS = re.compile(r"\b\d{7,}\b")

_MAX_DEPTH = 6


def _redact_text(value: str) -> str:
    """Scrub secrets that arrive embedded in a message rather than as their own field."""
    value = _BEARER.sub(f"Bearer {REDACTED}", value)
    value = _JWT.sub(REDACTED, value)
    value = _EMAIL.sub(REDACTED, value)
    return _LONG_DIGITS.sub(REDACTED, value)


def _is_sensitive(key: str) -> bool:
    """Whole-key matching, with the `X-` header prefix allowed for.

    Matching on a substring would redact `authorization_policy_version`, which is metadata worth
    keeping. Allowing the prefix catches `X-Access-Token`, which is the same thing as
    `access_token` arriving as a header.
    """
    normalised = key.lower().replace("-", "_")
    unprefixed = normalised[2:] if normalised.startswith("x_") else normalised
    return {normalised, unprefixed} & (REDACTED_KEYS | DROPPED_KEYS) != set()


def _redact_value(key: str, value: Any, depth: int) -> Any:
    if _is_sensitive(key):
        return REDACTED
    if key.lower().replace("-", "_") in SAFE_IDENTIFIER_KEYS:
        return value
    if depth >= _MAX_DEPTH:
        # Refuse to walk further rather than risk emitting something unexamined from deep inside a
        # structure. Truncating is safe; guessing is not.
        return "[truncated]"
    if isinstance(value, MutableMapping):
        return {k: _redact_value(str(k), v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(key, item, depth + 1) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def redact_processor(_logger: object, _method: str, event_dict: EventDict) -> EventDict:
    """Remove secrets, contact details and exact coordinates from every log line."""
    return {key: _redact_value(str(key), value, 0) for key, value in event_dict.items()}


def add_service_context(service_name: str, environment: str, version: str) -> Processor:
    """Stamp the fields that identify which process produced the line."""

    def processor(_logger: object, _method: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service_name)
        event_dict.setdefault("environment", environment)
        event_dict.setdefault("service_version", version)
        return event_dict

    return processor


def add_trace_context(_logger: object, _method: str, event_dict: EventDict) -> EventDict:
    """Attach the current OpenTelemetry ids so logs and traces can be joined.

    Imported lazily: the logging pipeline must keep working if tracing is not configured.
    """
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - tracing is an optional dependency
        return event_dict

    span = trace.get_current_span()
    context = span.get_span_context()
    if context.is_valid:
        event_dict.setdefault("trace_id", format(context.trace_id, "032x"))
        event_dict.setdefault("span_id", format(context.span_id, "016x"))
    return event_dict


def configure_logging(*, service_name: str, environment: str, version: str, level: str) -> None:
    """Install the JSON pipeline. Safe to call more than once; tests do."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        force=True,
    )

    # uvicorn's own access log would record the raw path with its query string, which is where a
    # coordinate would end up. This service logs access itself, after redaction.
    logging.getLogger("uvicorn.access").disabled = True

    # httpx logs every outbound request at INFO, including the full URL. Once this service proxies
    # geocoding, that URL contains a place name the user typed. Warnings and above still surface.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_service_context(service_name, environment, version),
            add_trace_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
