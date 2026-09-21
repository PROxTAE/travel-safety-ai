"""Bounded-cardinality service counters."""

from prometheus_client import Counter, Histogram

http_requests = Counter(
    "integration_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
http_latency = Histogram("integration_http_duration_seconds", "HTTP latency", ["method", "route"])
quarantined = Counter("integration_quarantined_total", "Quarantined records", ["error_code"])
snapshots_created = Counter(
    "integration_snapshots_created_total", "Snapshots stored, by quality gate", ["gate"]
)
snapshot_replays = Counter("integration_snapshot_replays_total", "Idempotent snapshot replays")
snapshot_build_seconds = Histogram(
    "integration_snapshot_build_seconds", "Pipeline time to build and store one snapshot"
)
quality_flags = Counter(
    "integration_quality_flags_total", "Quality flags on stored snapshots", ["flag"]
)
evidence_conflicts = Counter(
    "integration_evidence_conflicts_total", "Unresolved conflicts on stored snapshots"
)
evidence_coverage = Histogram(
    "integration_evidence_coverage_ratio",
    "Critical evidence coverage of stored snapshots",
    buckets=(0.0, 0.25, 0.5, 0.75, 0.9, 1.0),
)
evidence_freshness = Histogram(
    "integration_evidence_freshness_seconds",
    "Oldest critical source age of stored snapshots",
    buckets=(60, 300, 900, 3600, 21600, 86400, 604800),
)
evidence_age_unknown = Counter(
    "integration_evidence_age_unknown_total", "Stored snapshots whose critical source age is null"
)
requests_rejected = Counter(
    "integration_requests_rejected_total",
    "Requests rejected by contract validation, by field error code",
    ["code"],
)
