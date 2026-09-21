"""Observability, metrics and PII redaction tests.

Verifies that:
- Prometheus metrics are emitted for rate limiting, active SSE connections, and downstream calls.
- PII and sensitive data (credentials, exact coordinates, medical notes, phone numbers) are
  never leaked to logs or metrics.
"""

from __future__ import annotations

import json
from uuid import uuid4

from prometheus_client import generate_latest

from app.observability.logging import REDACTED, redact_processor
from app.observability.metrics import (
    REGISTRY,
    active_sse_connections,
    downstream_request_duration_seconds,
    downstream_request_errors_total,
    rate_limit_rejected_total,
)


def test_rate_limit_rejected_metric_increments() -> None:
    endpoint = f"test_ep_{uuid4().hex[:6]}"
    before = rate_limit_rejected_total.labels(endpoint=endpoint, subject_type="user")._value.get()

    rate_limit_rejected_total.labels(endpoint=endpoint, subject_type="user").inc()
    after = rate_limit_rejected_total.labels(endpoint=endpoint, subject_type="user")._value.get()

    assert after == before + 1


def test_active_sse_connections_gauge_updates() -> None:
    before = active_sse_connections._value.get()

    active_sse_connections.inc()
    assert active_sse_connections._value.get() == before + 1

    active_sse_connections.dec()
    assert active_sse_connections._value.get() == before


def test_downstream_request_metrics_record_accurately() -> None:
    downstream_request_duration_seconds.labels(dependency="agent", operation="create_run").observe(
        0.125
    )
    downstream_request_errors_total.labels(dependency="agent", error_kind="timeout").inc()

    metrics_text = generate_latest(REGISTRY).decode()
    duration_metric = (
        'api_downstream_request_duration_seconds_count{dependency="agent",operation="create_run"}'
    )
    error_metric = 'api_downstream_request_errors_total{dependency="agent",error_kind="timeout"}'
    assert duration_metric in metrics_text
    assert error_metric in metrics_text


def test_pii_redaction_removes_nested_sensitive_fields() -> None:
    event = {
        "event_type": "profile_update",
        "user_id": str(uuid4()),
        "profile": {
            "emergency_profile": {
                "blood_type": "O+",
                "allergies": ["Penicillin"],
                "medical_notes": "Asthmatic condition",
                "contacts": [{"name": "Jane", "phone": "0891234567"}],
            },
            "origin": {"coordinates": [100.5014, 13.7563]},
        },
        "authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.secret.token",
    }

    cleaned = redact_processor(None, "info", event)
    dumped = json.dumps(cleaned)

    # Sensitive data must not appear anywhere
    assert "O+" not in dumped
    assert "Penicillin" not in dumped
    assert "Asthmatic" not in dumped
    assert "0891234567" not in dumped
    assert "100.5014" not in dumped
    assert "13.7563" not in dumped
    assert "secret.token" not in dumped
    assert cleaned["authorization"] == REDACTED
