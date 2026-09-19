"""Prometheus metrics.

Labels are the whole design problem here: a label whose value comes from the request creates one
time series per distinct value, and a trip id would create one per trip until the scrape falls
over. So the route label is the *template* (`/api/v1/trips/{trip_id}`), never the path that was
actually requested, and no label carries a user id, a coordinate or anything else user-supplied.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

#: A registry of this service's own rather than the process-global default, so tests can build a
#: fresh one and metrics from an earlier test cannot leak into a later assertion.
REGISTRY = CollectorRegistry()

#: Buckets chosen around the budgets in the acceptance runbook: cached GET p95 under 300 ms,
#: assessment acknowledgement p95 under 500 ms. Without a bucket edge near the target, the
#: measurement cannot tell you whether the target was met.
_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0, 5.0, 10.0, 30.0)

http_requests_total = Counter(
    "api_http_requests_total",
    "HTTP requests handled, by route template, method and status class.",
    labelnames=("method", "route", "status"),
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "api_http_request_duration_seconds",
    "Wall-clock time to produce a response, by route template.",
    labelnames=("method", "route"),
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)

http_errors_total = Counter(
    "api_http_errors_total",
    "Responses carrying an error envelope, by contract error code.",
    labelnames=("route", "error_code"),
    registry=REGISTRY,
)

dependency_check_duration_seconds = Histogram(
    "api_dependency_check_duration_seconds",
    "Time taken by one readiness dependency check.",
    labelnames=("dependency",),
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 3.0),
    registry=REGISTRY,
)

dependency_up = Gauge(
    "api_dependency_up",
    "1 when a dependency answered its last readiness check, 0 when it did not.",
    labelnames=("dependency", "required"),
    registry=REGISTRY,
)

readiness_state = Gauge(
    "api_readiness_state",
    "1 when the service is ready to serve traffic, 0 when it is not.",
    registry=REGISTRY,
)

request_body_rejected_total = Counter(
    "api_request_body_rejected_total",
    "Requests refused before the body was read, by reason.",
    labelnames=("reason",),
    registry=REGISTRY,
)


def observe_request(*, method: str, route: str, status_code: int, duration_seconds: float) -> None:
    """Record one finished request.

    `route` must be the template. Passing a resolved path here is the mistake that turns a metrics
    endpoint into a memory leak.
    """
    http_requests_total.labels(method=method, route=route, status=str(status_code)).inc()
    http_request_duration_seconds.labels(method=method, route=route).observe(duration_seconds)


def observe_error(*, route: str, error_code: str) -> None:
    http_errors_total.labels(route=route, error_code=error_code).inc()
