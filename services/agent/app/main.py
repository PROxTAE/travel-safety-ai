"""FastAPI entrypoint for the agent service (module 03).

Wires together, in `lifespan`, everything `app/api/internal.py` depends on: the compiled graph
(`app/graph/builder.py`), the PostgreSQL checkpointer and `agent.runs` repository
(`app/checkpoints/postgres.py`), and the Redis progress publisher (`app/progress/publisher.py`).
Each is optional at the settings level (`DATABASE_URL`/`REDIS_URL` unset) so the service can still
start — degraded, and `/health/ready` says so — rather than crash-loop in an environment that has
not provisioned them yet; `require_internal_auth` still fails closed in production regardless.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from app import __version__
from app.api.internal import router as internal_runs_router
from app.checkpoints.postgres import (
    RunsRepository,
    agent_checkpointer,
    apply_migrations,
    normalize_conn_string,
)
from app.graph.builder import build_graph, graph_checksum
from app.progress.publisher import ProgressPublisher
from app.runtime import AppRuntime
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            checkpointer = None
            runs_repo = None
            publisher = None
            startup_error: str | None = None

            if resolved.database_url is not None:
                try:
                    norm_url = normalize_conn_string(resolved.database_url)
                    await apply_migrations(norm_url)
                    checkpointer = await stack.enter_async_context(agent_checkpointer(norm_url))
                    pool = AsyncConnectionPool(norm_url, min_size=1, max_size=5)
                    await stack.enter_async_context(pool)
                    runs_repo = RunsRepository(pool)
                except OSError as exc:
                    startup_error = f"database unavailable: {exc.__class__.__name__}"

            if resolved.redis_url is not None and startup_error is None:
                try:
                    redis = Redis.from_url(resolved.redis_url)
                    await redis.ping()
                    stack.push_async_callback(redis.aclose)
                    publisher = ProgressPublisher(redis, resolved.app_env)
                except OSError as exc:
                    startup_error = f"redis unavailable: {exc.__class__.__name__}"

            graph = build_graph(resolved, checkpointer)
            app.state.runtime = AppRuntime(
                settings=resolved,
                graph=graph,
                checkpointer=checkpointer,
                runs=runs_repo,
                publisher=publisher,
                startup_error=startup_error,
            )
            yield

    app = FastAPI(title="Smart Travel Agent", version=__version__, lifespan=lifespan)
    app.include_router(internal_runs_router)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": resolved.service_name, "version": __version__}

    @app.get("/health/ready")
    async def ready() -> Response:
        runtime: AppRuntime = app.state.runtime
        auth_ready = resolved.app_env != "production" or resolved.internal_service_token is not None
        database_configured = resolved.database_url is not None
        redis_configured = resolved.redis_url is not None
        database_ready = not database_configured or runtime.checkpointer is not None
        redis_ready = not redis_configured or runtime.publisher is not None
        ready_state = (
            runtime.startup_error is None and auth_ready and database_ready and redis_ready
        )
        body = {
            "status": "ready" if ready_state else "not_ready",
            "service": resolved.service_name,
            "graph_version": graph_checksum(),
            "database": "ready" if database_ready else "unavailable",
            "redis": "ready" if redis_ready else "unavailable",
            "error": runtime.startup_error,
        }
        return Response(
            content=json.dumps(body),
            media_type="application/json",
            status_code=200 if ready_state else 503,
        )

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
