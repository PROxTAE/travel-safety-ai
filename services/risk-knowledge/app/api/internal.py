from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from app.auth import require_internal_auth
from app.context import current_correlation_id, current_request_id
from app.contracts import (
    CapabilityState,
    EvidencePackageRequest,
    KnowledgeRetrieveData,
    KnowledgeRetrieveRequest,
    KnowledgeRetrieveResponse,
    KnowledgeStatusData,
    KnowledgeStatusResponse,
    ModelStatusData,
    ModelStatusResponse,
    RiskAssessData,
    RiskAssessRequest,
    RiskAssessResponse,
    RouteEvaluateData,
    RouteEvaluateRequest,
    RouteEvaluateResponse,
    StandardMeta,
)
from app.errors import ServiceError
from app.metrics import DEGRADED_RESULTS
from app.repositories.assessments import (
    save_fallback_assessments,
    save_fallback_route_evaluations,
)
from app.risk.fallback import assess_with_conservative_fallback
from app.routes.fallback import (
    FALLBACK_ROUTE_POLICY_VERSION,
    enforce_hard_constraints_without_ranking,
)

router = APIRouter(
    prefix="/internal/v1",
    dependencies=[Depends(require_internal_auth)],
)


def _meta(*, degraded_services: list[str] | None = None) -> StandardMeta:
    return StandardMeta(
        request_id=current_request_id(),
        correlation_id=current_correlation_id(),
        generated_at=datetime.now(UTC),
        degraded_services=degraded_services or [],
    )


@router.post("/risk/assess", response_model=RiskAssessResponse)
async def assess_risk(payload: RiskAssessRequest, request: Request) -> RiskAssessResponse:
    runtime = request.app.state.runtime
    if runtime.database.sessions is None:
        raise ServiceError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="Risk assessments cannot be persisted because the database is unavailable.",
            retryable=True,
            retry_after_seconds=5,
        )
    assessments = assess_with_conservative_fallback(payload.snapshot, payload.route_ids)
    try:
        async with runtime.database.sessions() as session:
            await save_fallback_assessments(
                session,
                assessments=assessments,
                input_hash=payload.snapshot.content_hash,
            )
    except Exception as exc:
        raise ServiceError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="Risk assessments could not be persisted.",
            retryable=True,
            retry_after_seconds=5,
        ) from exc
    DEGRADED_RESULTS.labels("risk_model", "MODEL_UNAVAILABLE").inc()
    return RiskAssessResponse(
        data=RiskAssessData(
            assessments=assessments,
            capability=CapabilityState(
                capability="RISK_MODEL",
                status="DEGRADED",
                version="fallback-safety-1.0.0",
                reason=runtime.model.reason or "MODEL_INFERENCE_NOT_ENABLED",
            ),
            limitations=["MODEL_UNAVAILABLE"],
        ),
        meta=_meta(degraded_services=["risk-model"]),
    )


@router.post("/knowledge/retrieve", response_model=KnowledgeRetrieveResponse)
async def retrieve_knowledge(
    _payload: KnowledgeRetrieveRequest, request: Request
) -> KnowledgeRetrieveResponse:
    runtime = request.app.state.runtime
    DEGRADED_RESULTS.labels("knowledge_retrieval", "NO_RELIABLE_KNOWLEDGE_EVIDENCE").inc()
    return KnowledgeRetrieveResponse(
        data=KnowledgeRetrieveData(
            evidence=[],
            capability=CapabilityState(
                capability="KNOWLEDGE_RETRIEVAL",
                status="UNAVAILABLE",
                version=runtime.knowledge.collection_version,
                reason=runtime.knowledge.reason or "RETRIEVAL_NOT_ENABLED",
            ),
            limitations=["NO_RELIABLE_KNOWLEDGE_EVIDENCE"],
        ),
        meta=_meta(degraded_services=["knowledge-retrieval"]),
    )


@router.post("/routes/evaluate", response_model=RouteEvaluateResponse)
async def evaluate_routes(payload: RouteEvaluateRequest, request: Request) -> RouteEvaluateResponse:
    runtime = request.app.state.runtime
    if runtime.database.sessions is None:
        raise ServiceError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="Route evaluations cannot be persisted because the database is unavailable.",
            retryable=True,
            retry_after_seconds=5,
        )
    routes, unusable = enforce_hard_constraints_without_ranking(
        payload.snapshot.route_candidates, payload.route_ids
    )
    try:
        selected_routes = [
            route
            for route in payload.snapshot.route_candidates
            if route.route_id in set(payload.route_ids)
        ]
        async with runtime.database.sessions() as session:
            await save_fallback_route_evaluations(
                session,
                snapshot_id=payload.snapshot.snapshot_id,
                routes=selected_routes,
                unusable_route_ids=unusable,
                policy_version=FALLBACK_ROUTE_POLICY_VERSION,
                input_hash=payload.snapshot.content_hash,
            )
    except Exception as exc:
        raise ServiceError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="Route evaluations could not be persisted.",
            retryable=True,
            retry_after_seconds=5,
        ) from exc
    DEGRADED_RESULTS.labels("route_evaluation", "ROUTE_RANKING_UNAVAILABLE").inc()
    return RouteEvaluateResponse(
        data=RouteEvaluateData(
            routes=routes,
            unusable_route_ids=unusable,
            capability=CapabilityState(
                capability="ROUTE_EVALUATION",
                status="DEGRADED",
                version=FALLBACK_ROUTE_POLICY_VERSION,
                reason=(
                    "Only official hard constraints are enforced until policy "
                    "coefficients are approved."
                ),
            ),
            policy_version=FALLBACK_ROUTE_POLICY_VERSION,
            limitations=["ROUTE_RANKING_UNAVAILABLE"],
        ),
        meta=_meta(degraded_services=["route-ranking"]),
    )


@router.post("/evidence/package")
async def create_evidence_package(_payload: EvidencePackageRequest, _request: Request) -> None:
    raise ServiceError(
        status_code=503,
        code="DEPENDENCY_UNAVAILABLE",
        message=(
            "Combined evidence packaging is unavailable until snapshot retrieval is configured."
        ),
        retryable=False,
    )


@router.get("/models/current", response_model=ModelStatusResponse)
async def current_model(request: Request) -> ModelStatusResponse:
    status = await request.app.state.runtime.refresh_model()
    return ModelStatusResponse(
        data=ModelStatusData(status=status.status, reason=status.reason, model=status.model),
        meta=_meta(degraded_services=[] if status.status == "AVAILABLE" else ["risk-model"]),
    )


@router.get("/knowledge/status", response_model=KnowledgeStatusResponse)
async def knowledge_status(request: Request) -> KnowledgeStatusResponse:
    status = await request.app.state.runtime.refresh_knowledge()
    return KnowledgeStatusResponse(
        data=KnowledgeStatusData(
            status=status.status,
            reason=status.reason,
            collection_version=status.collection_version,
            document_cutoff=status.document_cutoff,
        ),
        meta=_meta(
            degraded_services=[] if status.status == "AVAILABLE" else ["knowledge-retrieval"]
        ),
    )
