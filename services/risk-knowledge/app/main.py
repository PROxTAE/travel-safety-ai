from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.context import RequestContextMiddleware
from app.errors import install_error_handlers
from app.logging import configure_logging, get_logger
from app.observability import configure_tracing
from app.runtime import RuntimeState
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None, runtime: RuntimeState | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    resolved_runtime = runtime or RuntimeState(resolved_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        get_logger(environment=resolved_settings.app_env).info(
            "service_starting", status="starting"
        )
        await resolved_runtime.warmup()
        yield
        await resolved_runtime.close()

    app = FastAPI(
        title="Smart Travel Risk and Knowledge",
        version=__version__,
        docs_url=None if resolved_settings.app_env == "production" else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.runtime = resolved_runtime
    app.state.json_dumps = lambda value: json.dumps(value, separators=(",", ":"))
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(internal_router)
    configure_tracing(app, resolved_settings)
    return app


app = create_app()
