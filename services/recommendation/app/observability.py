from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from prometheus_client import Counter, Gauge, Histogram

# Prometheus Metrics
RECOMMENDATION_REQUESTS_TOTAL = Counter(
    "recommendation_requests_total",
    "Total number of recommendation requests composed",
    ["action", "risk", "status"],
)

RECOMMENDATION_LATENCY_SECONDS = Histogram(
    "recommendation_latency_seconds",
    "Latency of recommendation response builder in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

FEEDBACK_SUBMISSIONS_TOTAL = Counter(
    "feedback_submissions_total",
    "Total feedback submissions received",
    ["category"],
)

SAFETY_REVIEW_QUEUE_SIZE = Gauge(
    "safety_review_queue_size",
    "Current number of items in the safety review queue",
    ["status"],
)

ALERT_EVALUATIONS_TOTAL = Counter(
    "alert_evaluations_total",
    "Total alert reassessment evaluations performed",
    ["meaningful_change"],
)

ALERT_DELIVERIES_TOTAL = Counter(
    "alert_deliveries_total",
    "Total notifications delivered by channel",
    ["channel", "status"],
)

ALERT_DELIVERY_LATENCY_SECONDS = Histogram(
    "alert_delivery_latency_seconds",
    "Delivery latency by notification channel in seconds",
    ["channel"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

EMERGENCY_CONTACTS_LOOKUPS_TOTAL = Counter(
    "emergency_contacts_lookups_total",
    "Total emergency contacts directory lookups",
    ["country", "status"],
)


# PII Redaction regexes
_PHONE_PATTERN = re.compile(r"(\+?\d{1,4}[-.\s]?)?(\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4}")
_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_COORDINATE_PATTERN = re.compile(r"\[-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?\]")


def redact_pii_string(text: str | None) -> str | None:
    if not text:
        return text
    # Redact emails
    text = _EMAIL_PATTERN.sub("[EMAIL_REDACTED]", text)
    # Redact coordinates
    text = _COORDINATE_PATTERN.sub("[COORD_REDACTED]", text)

    # Redact phone numbers (if longer than 6 digits)
    def _replace_phone(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) >= 7:
            return "[PHONE_REDACTED]"
        return match.group(0)

    text = _PHONE_PATTERN.sub(_replace_phone, text)
    return text


def sanitize_log_event(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    # Redact sensitive keys if present in logs
    sensitive_keys = {"token", "authorization", "password", "secret", "cookie", "key"}
    for k, v in list(event_dict.items()):
        if any(s in k.lower() for s in sensitive_keys):
            event_dict[k] = "[REDACTED]"
        elif isinstance(v, str):
            event_dict[k] = redact_pii_string(v)
    return event_dict


def setup_observability(log_level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            sanitize_log_event,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
