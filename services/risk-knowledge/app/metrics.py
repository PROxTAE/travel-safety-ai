from prometheus_client import Counter, Gauge, Histogram

REQUEST_COUNT = Counter(
    "risk_knowledge_http_requests_total",
    "HTTP requests handled by the risk and knowledge service.",
    ("method", "route", "status"),
)
REQUEST_LATENCY = Histogram(
    "risk_knowledge_http_request_duration_seconds",
    "HTTP request latency.",
    ("method", "route"),
)
DEPENDENCY_STATUS = Gauge(
    "risk_knowledge_dependency_ready",
    "Dependency readiness (1 ready, 0 unavailable).",
    ("dependency",),
)
DEGRADED_RESULTS = Counter(
    "risk_knowledge_degraded_results_total",
    "Responses that used a conservative degraded path.",
    ("capability", "reason"),
)
ARTIFACT_VERIFICATION = Counter(
    "risk_knowledge_artifact_verification_total",
    "Model artifact verification outcomes.",
    ("status", "reason"),
)
