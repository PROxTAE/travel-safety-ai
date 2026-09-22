from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app import __version__
from app.cache import DecisionCache, IdempotencyConflict, input_hash
from app.domain.models import DecisionRequest, DecisionResult
from app.llm.service import explain_result
from app.policy.evaluator import build_result, evaluate
from app.policy.loader import Policy, load_policy
from app.repositories.audit import write_audit
from app.repositories.migrations import apply_migrations
from app.repositories.replay import load_audit_replay
from app.settings import Settings, get_settings

DECISIONS = Counter("decision_engine_decisions_total", "Locked decisions", ["action"])
EXPLANATION_FALLBACKS = Counter(
    "decision_engine_explanation_fallbacks_total", "Explanation fallbacks"
)
CACHE_HITS = Counter("decision_engine_cache_hits_total", "Decision cache hits", ["kind"])
CACHE_MISSES = Counter("decision_engine_cache_misses_total", "Decision cache misses", ["kind"])
DECISION_LATENCY = Histogram("decision_engine_latency_seconds", "End-to-end decision latency")
POLICY_FAILURES = Counter("decision_engine_policy_failures_total", "Policy load failures")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    state: dict[str, Policy | str | asyncpg.Pool | Redis | DecisionCache | None] = {
        "policy": None,
        "checksum": None,
        "error": None,
        "database": None,
        "cache": None,
    }

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        try:
            policy, checksum = load_policy(resolved.policy_path, resolved.policy_checksum)
            state.update(policy=policy, checksum=checksum, error=None)
        except (OSError, ValueError) as exc:
            POLICY_FAILURES.inc()
            state["error"] = str(exc)
        if resolved.database_url:
            try:
                pool = await asyncpg.create_pool(
                    resolved.database_url, min_size=1, max_size=5, command_timeout=3
                )
                assert pool is not None
                state["database"] = pool
                await apply_migrations(pool, resolved.migrations_path)
            except (OSError, asyncpg.PostgresError) as exc:
                state["error"] = f"database unavailable: {exc.__class__.__name__}"
        if resolved.redis_url:
            try:
                redis = Redis.from_url(resolved.redis_url, decode_responses=True)
                await redis.ping()
                state["cache"] = DecisionCache(redis, resolved.cache_ttl_seconds)
            except RedisError as exc:
                state["error"] = f"cache unavailable: {exc.__class__.__name__}"
        yield
        database = state["database"]
        if isinstance(database, asyncpg.Pool):
            await database.close()
        cache = state["cache"]
        if isinstance(cache, DecisionCache):
            await cache.redis.aclose()

    app = FastAPI(title="Smart Travel Decision Engine", version=__version__, lifespan=lifespan)
    app.state.settings = resolved
    app.state.decision_state = state

    async def require_internal_auth(authorization: str | None = Header(default=None)) -> None:
        if resolved.internal_service_token is None:
            if resolved.app_env == "production":
                raise HTTPException(
                    status_code=503, detail="Internal authentication is unavailable"
                )
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
        database_ready = resolved.database_url is None or isinstance(
            state["database"], asyncpg.Pool
        )
        ready_state = (
            policy is not None
            and database_ready
            and (resolved.app_env != "production" or resolved.internal_auth_configured)
        )
        cache = state["cache"]
        cache_status = (
            "ready"
            if isinstance(cache, DecisionCache)
            else ("disabled" if resolved.redis_url is None else "unavailable")
        )
        body = {
            "status": "ready" if ready_state else "not_ready",
            "service": "decision-engine",
            "policy": getattr(policy, "version", None),
            "database": "ready" if database_ready else "unavailable",
            "cache": cache_status,
            "error": state["error"],
        }
        return Response(
            content=json.dumps(body),
            media_type="application/json",
            status_code=200 if ready_state else 503,
        )

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/internal/v1/policy")
    async def policy_metadata(_: None = Depends(require_internal_auth)) -> dict[str, object]:
        policy = state["policy"]
        if not isinstance(policy, Policy):
            raise HTTPException(status_code=503, detail="Approved decision policy is unavailable")
        return {
            "version": policy.version,
            "contract_version": policy.contract_version,
            "status": policy.status,
            "checksum": state["checksum"],
            "thresholds": policy.thresholds.model_dump(),
        }

    @app.get("/internal/v1/audit/{audit_id}")
    async def audit_replay(
        audit_id: str, _: None = Depends(require_internal_auth)
    ) -> dict[str, object]:
        database = state["database"]
        if not isinstance(database, asyncpg.Pool):
            raise HTTPException(status_code=503, detail="Audit database is unavailable")
        try:
            from uuid import UUID

            replay = await load_audit_replay(database, UUID(audit_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid audit id") from exc
        if replay is None:
            raise HTTPException(status_code=404, detail="Audit event not found")
        return replay.model_dump(mode="json")

    class ValidationRequest(BaseModel):
        result: DecisionResult
        locked_action: str

    @app.post("/internal/v1/decisions/validate")
    async def validate_decision(
        payload: ValidationRequest, _: None = Depends(require_internal_auth)
    ) -> dict[str, object]:
        action_matches = payload.result.action_code.value == payload.locked_action
        valid = action_matches and all(payload.result.validation.values())
        return {
            "valid": valid,
            "locked_action": action_matches,
            "schema": True,
            "citations": payload.result.validation.get("citations", False),
        }

    @app.post("/internal/v1/decisions", response_model=DecisionResult)
    async def decide(
        payload: DecisionRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _: None = Depends(require_internal_auth),
    ) -> DecisionResult:
        started = time.perf_counter()
        policy = state["policy"]
        if not isinstance(policy, Policy):
            raise HTTPException(status_code=503, detail="Approved decision policy is unavailable")
        cache = state["cache"]
        model = (
            resolved.openai_explainer_model
            if resolved.openai_enabled and resolved.openai_api_key
            else None
        )
        request_hash = input_hash(payload, policy, "1.0.0", model)
        if isinstance(cache, DecisionCache):
            try:
                if idempotency_key:
                    existing = await cache.reserve_idempotency(idempotency_key, request_hash)
                    if existing:
                        CACHE_HITS.labels("idempotency").inc()
                        DECISION_LATENCY.observe(time.perf_counter() - started)
                        return existing
                    CACHE_MISSES.labels("idempotency").inc()
                cached = await cache.get_explanation(request_hash)
                if cached:
                    CACHE_HITS.labels("explanation").inc()
                    DECISION_LATENCY.observe(time.perf_counter() - started)
                    return cached
                CACHE_MISSES.labels("explanation").inc()
            except (RedisError, IdempotencyConflict) as exc:
                if isinstance(exc, IdempotencyConflict):
                    raise HTTPException(status_code=409, detail="Idempotency-Key conflict") from exc
        result = build_result(payload, policy, evaluate(payload, policy))
        explained_result = await explain_result(result, payload.locale, resolved)
        if explained_result.versions.get("llm_model") is None:
            EXPLANATION_FALLBACKS.inc()
        result = explained_result
        if isinstance(cache, DecisionCache):
            try:
                await cache.set_explanation(request_hash, result)
                if idempotency_key:
                    await cache.save_idempotency(idempotency_key, request_hash, result)
            except RedisError:
                pass
        database = state["database"]
        if isinstance(database, asyncpg.Pool):
            try:
                await write_audit(database, result, str(state["checksum"]))
            except asyncpg.PostgresError as exc:
                raise HTTPException(
                    status_code=503, detail=f"Decision audit unavailable: {exc.__class__.__name__}"
                ) from exc
        DECISIONS.labels(result.action_code.value).inc()
        DECISION_LATENCY.observe(time.perf_counter() - started)
        return result

    return app


app = create_app()
