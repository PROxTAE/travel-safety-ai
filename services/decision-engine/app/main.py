from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
import asyncpg
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from app import __version__
from app.domain.models import DecisionRequest, DecisionResult
from app.policy.evaluator import build_result, evaluate
from app.policy.loader import Policy, load_policy
from app.repositories.audit import write_audit
from app.repositories.migrations import apply_migrations
from app.settings import Settings, get_settings

DECISIONS = Counter("decision_engine_decisions_total", "Locked decisions", ["action"])
POLICY_FAILURES = Counter("decision_engine_policy_failures_total", "Policy load failures")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    state: dict[str, Policy | str | asyncpg.Pool | None] = {"policy": None, "checksum": None, "error": None, "database": None}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            policy, checksum = load_policy(resolved.policy_path, resolved.policy_checksum)
            state.update(policy=policy, checksum=checksum, error=None)
        except (OSError, ValueError) as exc:
            POLICY_FAILURES.inc()
            state["error"] = str(exc)
        if resolved.database_url:
            try:
                state["database"] = await asyncpg.create_pool(
                    resolved.database_url, min_size=1, max_size=5, command_timeout=3
                )
                await apply_migrations(state["database"], resolved.migrations_path)
            except (OSError, asyncpg.PostgresError) as exc:
                state["error"] = f"database unavailable: {exc.__class__.__name__}"
        yield
        database = state["database"]
        if isinstance(database, asyncpg.Pool):
            await database.close()

    app = FastAPI(title="Smart Travel Decision Engine", version=__version__, lifespan=lifespan)
    app.state.settings = resolved
    app.state.decision_state = state

    async def require_internal_auth(authorization: str | None = Header(default=None)) -> None:
        if resolved.internal_service_token is None:
            if resolved.app_env == "production":
                raise HTTPException(status_code=503, detail="Internal authentication is unavailable")
            return
        expected = f"Bearer {resolved.internal_service_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Authentication required")

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": "decision-engine", "version": resolved.service_version}

    @app.get("/health/ready")
    async def ready() -> Response:
        policy = state["policy"]
        database_ready = resolved.database_url is None or isinstance(state["database"], asyncpg.Pool)
        ready_state = policy is not None and database_ready and (resolved.app_env != "production" or resolved.internal_auth_configured)
        body = {"status": "ready" if ready_state else "not_ready", "service": "decision-engine", "policy": getattr(policy, "version", None), "database": "ready" if database_ready else "unavailable", "error": state["error"]}
        return Response(content=json.dumps(body), media_type="application/json", status_code=200 if ready_state else 503)

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/internal/v1/policy")
    async def policy_metadata(_: None = Depends(require_internal_auth)) -> dict[str, object]:
        policy = state["policy"]
        if not isinstance(policy, Policy):
            raise HTTPException(status_code=503, detail="Approved decision policy is unavailable")
        return {"version": policy.version, "contract_version": policy.contract_version, "status": policy.status, "checksum": state["checksum"], "thresholds": policy.thresholds.model_dump()}

    @app.post("/internal/v1/decisions", response_model=DecisionResult)
    async def decide(payload: DecisionRequest, _: None = Depends(require_internal_auth)) -> DecisionResult:
        policy = state["policy"]
        if not isinstance(policy, Policy):
            raise HTTPException(status_code=503, detail="Approved decision policy is unavailable")
        result = build_result(payload, policy, evaluate(payload, policy))
        database = state["database"]
        if isinstance(database, asyncpg.Pool):
            try:
                await write_audit(database, result, str(state["checksum"]))
            except asyncpg.PostgresError as exc:
                raise HTTPException(status_code=503, detail=f"Decision audit unavailable: {exc.__class__.__name__}") from exc
        DECISIONS.labels(result.action_code.value).inc()
        return result

    return app


app = create_app()