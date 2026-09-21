from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.auth import require_internal_auth
from app.context import current_correlation_id, current_request_id
from app.contracts import (
    CapabilityState,
    EvidencePackageData,
    EvidencePackageRequest,
    EvidencePackageResponse,
    EvidenceVersions,
    KnowledgeRetrieveData,
    KnowledgeRetrieveRequest,
    KnowledgeRetrieveResponse,
    KnowledgeStatusData,
    KnowledgeStatusResponse,
    ModelStatusData,
    ModelStatusResponse,
    RiskAssessData,
    RiskAssessment,
    RiskAssessRequest,
    RiskAssessResponse,
    RouteCandidate,
    RouteEvaluateData,
    RouteEvaluateRequest,
    RouteEvaluateResponse,
    StandardMeta,
    validate_route_selection,
)
from app.errors import ServiceError
from app.integrations.snapshots import SnapshotUnavailable
from app.knowledge.pipeline import dense_vector, resolve_citation
from app.metrics import DEGRADED_RESULTS
from app.repositories.assessments import (
    save_fallback_assessments,
    save_fallback_route_evaluations,
)
from app.risk.fallback import assess_with_conservative_fallback
from app.risk.inference import ModelInputRejected
from app.routes.evaluation import evaluate_snapshot_routes
from app.routes.fallback import FALLBACK_ROUTE_POLICY_VERSION
from app.routes.policy import load_approved_severity_weights

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
    predictor = getattr(runtime, "predictor", None)
    limitations: list[str] = []
    degraded = predictor is None
    if predictor is None:
        assessments = assess_with_conservative_fallback(payload.snapshot, payload.route_ids)
        limitations = ["MODEL_UNAVAILABLE"]
    else:
        try:
            assessments = predictor.assess(payload.snapshot, payload.route_ids)
        except ModelInputRejected:
            assessments = assess_with_conservative_fallback(payload.snapshot, payload.route_ids)
            limitations = ["FEATURE_SCHEMA_OR_QUALITY_REJECTED"]
            degraded = True
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
    if degraded:
        DEGRADED_RESULTS.labels("risk_model", "MODEL_UNAVAILABLE").inc()
    return RiskAssessResponse(
        data=RiskAssessData(
            assessments=assessments,
            capability=CapabilityState(
                capability="RISK_MODEL",
                status="DEGRADED" if degraded else "AVAILABLE",
                version=("fallback-safety-1.0.0" if degraded else runtime.model.model.version),
                reason=(runtime.model.reason or "MODEL_INFERENCE_NOT_ENABLED")
                if degraded
                else None,
            ),
            limitations=limitations,
        ),
        meta=_meta(degraded_services=["risk-model"] if degraded else []),
    )


@router.post("/knowledge/retrieve", response_model=KnowledgeRetrieveResponse)
async def retrieve_knowledge(
    payload: KnowledgeRetrieveRequest, request: Request
) -> KnowledgeRetrieveResponse:
    runtime = request.app.state.runtime
    evidence: list[dict[str, object]] = []
    if runtime.knowledge.status == "AVAILABLE":
        try:
            searches = [
                runtime.qdrant.search(
                    vector=dense_vector(
                        f"{hazard} {payload.action_code}",
                        dimensions=runtime.settings.qdrant_vector_size,
                    ),
                    region=country,
                    language=payload.locale.split("-")[0],
                    hazard=hazard,
                    at=payload.at,
                    limit=payload.limit,
                )
                for hazard in payload.hazards
                for country in payload.country_codes
            ]
            batches = await asyncio.gather(*searches)
            seen: set[tuple[object, object]] = set()
            for item in (entry for batch in batches for entry in batch):
                key = (item.get("document_id"), item.get("content_hash"))
                if key in seen:
                    continue
                seen.add(key)
                item["citation"] = resolve_citation(item)
                evidence.append(item)
            evidence = evidence[: payload.limit]
        except Exception:
            evidence = []
    available = bool(evidence)
    if not available:
        DEGRADED_RESULTS.labels("knowledge_retrieval", "NO_RELIABLE_KNOWLEDGE_EVIDENCE").inc()
    return KnowledgeRetrieveResponse(
        data=KnowledgeRetrieveData(
            evidence=evidence,
            capability=CapabilityState(
                capability="KNOWLEDGE_RETRIEVAL",
                status="AVAILABLE" if available else "UNAVAILABLE",
                version=runtime.knowledge.collection_version,
                reason=None if available else runtime.knowledge.reason or "NO_MATCHING_EVIDENCE",
            ),
            limitations=[] if available else ["NO_RELIABLE_KNOWLEDGE_EVIDENCE"],
        ),
        meta=_meta(degraded_services=[] if available else ["knowledge-retrieval"]),
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
    policy_version, weights = load_approved_severity_weights(runtime.settings.route_policy_path)
    evaluated = evaluate_snapshot_routes(payload.snapshot, payload.route_ids, weights)
    routes = [item.route for item in evaluated]
    unusable = [
        UUID(str(item.route.route_id))
        for item in evaluated
        if not item.usable and isinstance(item.route.route_id, UUID)
    ]
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
                policy_version=policy_version,
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
    degraded = weights is None
    if degraded:
        DEGRADED_RESULTS.labels("route_evaluation", "ROUTE_RANKING_UNAVAILABLE").inc()
    return RouteEvaluateResponse(
        data=RouteEvaluateData(
            routes=routes,
            unusable_route_ids=unusable,
            capability=CapabilityState(
                capability="ROUTE_EVALUATION",
                status="DEGRADED" if degraded else "AVAILABLE",
                version=policy_version,
                reason=(
                    "Only official hard constraints are enforced until policy "
                    "coefficients are approved."
                )
                if degraded
                else None,
            ),
            policy_version=policy_version,
            limitations=["ROUTE_RANKING_UNAVAILABLE"] if degraded else [],
        ),
        meta=_meta(degraded_services=["route-ranking"] if degraded else []),
    )


@router.post("/evidence/package", response_model=EvidencePackageResponse)
async def create_evidence_package(
    payload: EvidencePackageRequest, request: Request
) -> EvidencePackageResponse:
    runtime = request.app.state.runtime
    try:
        snapshot = await runtime.snapshots.get(payload.snapshot_id)
    except SnapshotUnavailable as exc:
        raise ServiceError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message="The immutable snapshot could not be read safely.",
            retryable=True,
            retry_after_seconds=5,
        ) from exc
    available_ids = [
        route.route_id for route in snapshot.route_candidates if isinstance(route.route_id, UUID)
    ]
    route_ids = payload.route_ids or available_ids
    try:
        validate_route_selection(snapshot, route_ids)
    except ValueError as exc:
        raise ServiceError(
            status_code=400,
            code="INVALID_ROUTE_SELECTION",
            message=str(exc),
            retryable=False,
        ) from exc

    async def risk_part() -> tuple[list[RiskAssessment], CapabilityState, list[str]]:
        if runtime.predictor is None:
            values = assess_with_conservative_fallback(snapshot, route_ids)
            return (
                values,
                CapabilityState(
                    capability="RISK_MODEL",
                    status="DEGRADED",
                    version="fallback-safety-1.0.0",
                    reason="MODEL_UNAVAILABLE",
                ),
                ["MODEL_UNAVAILABLE"],
            )
        try:
            values = await asyncio.to_thread(runtime.predictor.assess, snapshot, route_ids)
            return (
                values,
                CapabilityState(
                    capability="RISK_MODEL",
                    status="AVAILABLE",
                    version=runtime.model.model.version if runtime.model.model else None,
                    reason=None,
                ),
                [],
            )
        except ModelInputRejected:
            values = assess_with_conservative_fallback(snapshot, route_ids)
            return (
                values,
                CapabilityState(
                    capability="RISK_MODEL",
                    status="DEGRADED",
                    version="fallback-safety-1.0.0",
                    reason="FEATURE_SCHEMA_OR_QUALITY_REJECTED",
                ),
                ["FEATURE_SCHEMA_OR_QUALITY_REJECTED"],
            )

    async def knowledge_part() -> tuple[list[dict[str, object]], CapabilityState, list[str]]:
        hazards = [
            str(item.get("event_type") or item.get("hazard") or "UNKNOWN")
            for item in snapshot.disaster_events
        ] or ["UNKNOWN"]
        if runtime.knowledge.status != "AVAILABLE":
            return (
                [],
                CapabilityState(
                    capability="KNOWLEDGE_RETRIEVAL",
                    status="UNAVAILABLE",
                    version=runtime.knowledge.collection_version,
                    reason=runtime.knowledge.reason or "NO_ACTIVE_KNOWLEDGE_COLLECTION",
                ),
                ["NO_RELIABLE_KNOWLEDGE_EVIDENCE"],
            )
        batches = await asyncio.gather(
            *[
                runtime.qdrant.search(
                    vector=dense_vector(hazard, dimensions=runtime.settings.qdrant_vector_size),
                    region=None,
                    language=payload.locale.split("-")[0],
                    hazard=hazard,
                    at=snapshot.travel_window.starts_at,
                    limit=5,
                )
                for hazard in hazards
            ],
            return_exceptions=True,
        )
        evidence = [item for batch in batches if isinstance(batch, list) for item in batch]
        if not evidence:
            return (
                [],
                CapabilityState(
                    capability="KNOWLEDGE_RETRIEVAL",
                    status="DEGRADED",
                    version=runtime.knowledge.collection_version,
                    reason="NO_MATCHING_EVIDENCE",
                ),
                ["NO_RELIABLE_KNOWLEDGE_EVIDENCE"],
            )
        return (
            evidence,
            CapabilityState(
                capability="KNOWLEDGE_RETRIEVAL",
                status="AVAILABLE",
                version=runtime.knowledge.collection_version,
                reason=None,
            ),
            [],
        )

    async def route_part() -> tuple[list[RouteCandidate], CapabilityState, list[str]]:
        policy_version, weights = load_approved_severity_weights(runtime.settings.route_policy_path)
        values = await asyncio.to_thread(evaluate_snapshot_routes, snapshot, route_ids, weights)
        return (
            [item.route for item in values],
            CapabilityState(
                capability="ROUTE_EVALUATION",
                status="AVAILABLE" if weights else "DEGRADED",
                version=policy_version,
                reason=None if weights else "ROUTE_RANKING_UNAVAILABLE",
            ),
            [] if weights else ["ROUTE_RANKING_UNAVAILABLE"],
        )

    risk_result, knowledge_result, route_result = await asyncio.gather(
        risk_part(), knowledge_part(), route_part()
    )
    limitations = list(dict.fromkeys(risk_result[2] + knowledge_result[2] + route_result[2]))
    capabilities = [risk_result[1], knowledge_result[1], route_result[1]]
    return EvidencePackageResponse(
        data=EvidencePackageData(
            snapshot_id=snapshot.snapshot_id,
            assessments=risk_result[0],
            evidence=knowledge_result[0],
            routes=route_result[0],
            capabilities=capabilities,
            limitations=limitations,
            versions=EvidenceVersions(
                feature_schema=snapshot.feature_schema_version,
                model=runtime.model.model.version if runtime.model.model else None,
                thresholds=None,
                route_policy=route_result[1].version or FALLBACK_ROUTE_POLICY_VERSION,
                knowledge_collection=runtime.knowledge.collection_version,
            ),
        ),
        meta=_meta(
            degraded_services=[
                item.capability for item in capabilities if item.status != "AVAILABLE"
            ]
        ),
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
