"""OpenTelemetry setup.

Tracing is optional by design: with no collector configured the SDK still runs, spans are still
created and their ids still reach the logs, but nothing is exported. That keeps local development
and the test suite working without an extra container, while a single environment variable turns
export on.

The FastAPI instrumentation is told to skip the health and metrics endpoints. They are polled every
few seconds by the orchestrator and by Prometheus, and their spans would swamp any trace worth
looking at.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.settings import Settings

#: Polled constantly and uninteresting; excluded so traces stay readable.
_EXCLUDED_URLS = "health/live,health/ready,metrics"


def configure_tracing(settings: Settings) -> TracerProvider:
    """Install a tracer provider, exporting only when an endpoint is configured."""
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "service.version": settings.service_version,
            "deployment.environment": settings.app_env,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint))
        )

    trace.set_tracer_provider(provider)
    return provider


def instrument_app(app: FastAPI) -> None:
    """Attach automatic instrumentation.

    Each import is guarded: a missing optional instrumentation package must not stop the service
    from starting, because observability is not a reason to refuse traffic.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls=_EXCLUDED_URLS)
    except Exception:  # noqa: S110 - never fail startup over instrumentation
        pass

    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

        AsyncPGInstrumentor().instrument()  # type: ignore[no-untyped-call]
    except Exception:  # noqa: S110
        pass

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:  # noqa: S110
        pass
