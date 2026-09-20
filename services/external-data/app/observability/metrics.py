"""Prometheus metrics required by the observability contract § 12."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 30.0)

http_requests = Counter(
    "external_data_http_requests_total",
    "Internal HTTP requests handled",
    ["method", "route", "status"],
    registry=REGISTRY,
)
http_latency = Histogram(
    "external_data_http_request_duration_seconds",
    "Internal HTTP request latency",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)

provider_requests = Counter(
    "external_data_provider_requests_total",
    "Outbound provider requests",
    ["provider", "outcome"],
    registry=REGISTRY,
)
provider_latency = Histogram(
    "external_data_provider_duration_seconds",
    "Outbound provider latency",
    ["provider"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)
provider_errors = Counter(
    "external_data_provider_errors_total",
    "Outbound provider failures by contract error code",
    ["provider", "error_code"],
    registry=REGISTRY,
)
provider_retries = Counter(
    "external_data_provider_retries_total",
    "Retried provider attempts",
    ["provider"],
    registry=REGISTRY,
)
provider_timeouts = Counter(
    "external_data_provider_timeouts_total",
    "Provider calls that hit the deadline",
    ["provider"],
    registry=REGISTRY,
)
circuit_state = Gauge(
    "external_data_circuit_state",
    "Circuit breaker state (0 closed, 1 half-open, 2 open)",
    ["provider"],
    registry=REGISTRY,
)
quota_remaining = Gauge(
    "external_data_provider_quota_remaining",
    "Remaining provider quota in the current window, when the provider reports it",
    ["provider", "window"],
    registry=REGISTRY,
)

cache_events = Counter(
    "external_data_cache_events_total",
    "Cache outcomes",
    ["provider", "event"],  # hit | miss | negative_hit | stale_hit | store | lock_wait
    registry=REGISTRY,
)
degraded_results = Counter(
    "external_data_degraded_results_total",
    "Responses returned with at least one degraded provider",
    ["capability"],
    registry=REGISTRY,
)

# --- Phase 6: what a combined context request actually managed to gather ---
context_capabilities = Counter(
    "external_data_context_capabilities_total",
    "Outcome of each capability inside a combined /context/query request",
    # answered | unavailable | failed | timed_out | not_requested
    ["capability", "outcome"],
    registry=REGISTRY,
)
source_disagreements = Counter(
    "external_data_source_disagreements_total",
    "Groups where more than one provider reported what looks like the same "
    "event. Not an error: it is the signal that two sources are describing one "
    "hazard differently, which module 05 has to reconcile.",
    ["capability"],
    registry=REGISTRY,
)
