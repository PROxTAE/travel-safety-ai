from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import joblib
import pytest

from app.contracts import ModelReference, RiskLevel
from app.knowledge.pipeline import (
    HybridRetriever,
    KnowledgeChunk,
    download_approved_source,
    evaluate_retrieval,
    qdrant_points,
)
from app.risk.fallback import assess_with_conservative_fallback
from app.risk.inference import ModelInputRejected, RiskPredictor
from app.risk.monitoring import DriftWindow
from app.risk.overrides import enforce_official_priority, validate_monotonic_override
from app.routes.evaluation import evaluate_exposure, evaluate_snapshot_routes, rank_routes
from training.baseline import derive_high_threshold, train
from training.explain import linear_shap_values, validate_reason_mapping
from training.promote import promote
from training.release_check import verify_release


def _features(level: str, offset: int) -> dict[str, object]:
    return {
        "route_distance_m": 10000.0 + offset,
        "route_duration_seconds": 1200.0 + offset,
        "route_transfer_count": 0,
        "corridor_official_closure_active": level == "HIGH",
        "corridor_official_evacuation_active": None,
        "corridor_extreme_alert_active": level == "HIGH",
        "hazard_intersection_fraction": 0.4
        if level == "HIGH"
        else 0.05
        if level == "MEDIUM"
        else 0.0,
        "max_weather_severity_ordinal": 4 if level == "HIGH" else 2 if level == "MEDIUM" else 0,
        "max_precipitation_probability": 0.9
        if level == "HIGH"
        else 0.4
        if level == "MEDIUM"
        else 0.1,
        "max_wind_gust_kmh": 90.0 if level == "HIGH" else 55.0 if level == "MEDIUM" else 10.0,
        "transport_disruption_severity": 2 if level != "LOW" else 0,
        "critical_evidence_coverage": 1.0,
        "critical_evidence_freshness_seconds": 60,
    }


def test_training_candidate_is_reproducible_and_promotion_fails_closed(tmp_path: Path) -> None:
    rows = []
    for group in ("NORTH", "CENTRAL", "SOUTH"):
        for level in ("LOW", "MEDIUM", "HIGH"):
            for index in range(5):
                rows.append(
                    {
                        "row_id": f"{group}-{level}-{index}",
                        "geography_group": group,
                        "season": "MONSOON" if index % 2 else "DRY",
                        "hazard_type": "STORM" if level != "LOW" else "NONE",
                        "travel_mode": "CAR",
                        "features": _features(level, index),
                        "label": level,
                    }
                )
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "dataset_rows.json").write_text(json.dumps(rows), encoding="utf-8")
    (dataset / "dataset_manifest.json").write_text(
        json.dumps(
            {"content_checksum": "sha256:" + "a" * 64, "split": {"leakage_check_passed": True}}
        ),
        encoding="utf-8",
    )
    first = train(dataset, tmp_path / "out1")
    second = train(dataset, tmp_path / "out2")
    assert first.metrics["high_risk_recall"] >= 0.8
    assert first.metrics["rule_baseline"]["high_risk_recall"] == 1.0
    assert first.checksum == second.checksum
    assert 0 <= first.metrics["pr_auc"] <= 1
    assert derive_high_threshold(first.metrics, 0.8) in {0.1, 0.25, 0.5, 0.75, 0.9}
    with pytest.raises(ValueError, match="APPROVED_HIGH_RECALL_OBJECTIVE_REQUIRED"):
        derive_high_threshold(first.metrics, None)
    bundle = joblib.load(first.artifact)
    contributions = linear_shap_values(
        bundle,
        [_features("HIGH", 1)[name] for name in bundle["feature_names"]],
        "HIGH",
    )
    assert validate_reason_mapping(contributions, bundle["reason_codes"])
    acceptance = tmp_path / "acceptance.yaml"
    acceptance.write_text(
        (
            "status: PENDING_TEAM_LEAD_APPROVAL\n"
            "thresholds:\n"
            "  high_risk_recall_min: null\n"
            "  high_risk_false_negative_rate_max: null\n"
            "  expected_calibration_error_max: null\n"
        ),
        encoding="utf-8",
    )
    record = promote(first.manifest, acceptance, tmp_path / "promotion.json")
    assert record["stage"] == "CANDIDATE"
    assert "MODEL_ACCEPTANCE_NOT_APPROVED" in record["promotion_failures"]


def test_route_hard_constraint_precedes_ranking(snapshot) -> None:
    route = snapshot.route_candidates[0]
    hazard = {
        "event_id": "closure-1",
        "official": True,
        "closure": True,
        "severity": "EXTREME",
        "geometry": route.geometry,
    }
    evaluated = evaluate_exposure(route, [hazard], {"EXTREME": 1.0})
    assert evaluated.risk_level == RiskLevel.HIGH
    assert evaluated.exposure is not None and evaluated.exposure.closed
    ranked = rank_routes([evaluated])
    assert ranked[0].usable is False
    assert ranked[0].route.label == "ALTERNATIVE"


def test_release_check_refuses_unapproved_artifact(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"stage": "CANDIDATE"}), encoding="utf-8")
    card = tmp_path / "card.md"
    card.write_text("Reports associations, not causal effects.", encoding="utf-8")
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(json.dumps({"golden_cases_passed": True}), encoding="utf-8")
    result = verify_release(manifest, card, evaluation)
    assert result["ready"] is False
    assert "MODEL_NOT_ACTIVE" in result["failures"]


def test_release_check_accepts_complete_safety_evidence(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"stage": "ACTIVE"}), encoding="utf-8")
    card = tmp_path / "card.md"
    card.write_text("Reports associations, not causal effects.", encoding="utf-8")
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(
        json.dumps(
            {
                "golden_cases_passed": True,
                "no_expired_or_wrong_authority_citations": True,
                "no_closed_recommended_route": True,
                "rollback_test_passed": True,
                "latency_p95_ms": 120,
                "peak_memory_mb": 64,
                "concurrent_requests": 16,
            }
        ),
        encoding="utf-8",
    )
    assert verify_release(manifest, card, evaluation)["ready"] is True


def test_verified_predictor_rejects_missing_critical_and_predicts(tmp_path: Path, snapshot) -> None:
    rows = []
    for group in ("NORTH", "CENTRAL", "SOUTH"):
        for level in ("LOW", "MEDIUM", "HIGH"):
            for index in range(4):
                rows.append(
                    {
                        "row_id": f"{group}-{level}-{index}",
                        "geography_group": group,
                        "season": "WET",
                        "hazard_type": "STORM",
                        "travel_mode": "CAR",
                        "features": _features(level, index),
                        "label": level,
                    }
                )
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "dataset_rows.json").write_text(json.dumps(rows), encoding="utf-8")
    (dataset / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "content_checksum": "sha256:" + "b" * 64,
                "split": {"leakage_check_passed": True},
            }
        ),
        encoding="utf-8",
    )
    trained = train(dataset, tmp_path / "model")
    reference = ModelReference(
        name="route-risk-baseline",
        version="1.0.0",
        feature_schema_version="1.0.0",
        artifact_checksum=trained.checksum,
    )
    predictor = RiskPredictor(trained.artifact, reference)
    route_id = UUID(str(snapshot.route_candidates[0].route_id))
    with pytest.raises(ModelInputRejected, match="MISSING_CRITICAL_EVIDENCE"):
        predictor.assess(snapshot, [route_id])
    complete = snapshot.model_copy(update={"features": _features("LOW", 1)})
    assessments = predictor.assess(complete, [route_id])
    assert assessments[0].model.version == "1.0.0"
    assert assessments[0].risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH}


def test_monitoring_and_hybrid_retrieval() -> None:
    drift = DriftWindow("1.0.0")
    drift.observe("HIGH", ["weather"], location="TH", season="MONSOON", hazard="FLOOD")
    drift.observe_feedback("HIGH", "HIGH")
    assert drift.snapshot()["automatic_retraining"] is False
    assert drift.snapshot()["high_risk_recall_proxy"] == 1.0
    now = datetime.now(UTC)
    chunks = [
        KnowledgeChunk(
            "doc-1",
            "official flood evacuation procedure",
            2,
            "Evacuation",
            "GOVERNMENT",
            "https://example.gov/guide.pdf",
            "en",
            ("TH",),
            ("FLOOD",),
            now - timedelta(days=1),
            now + timedelta(days=1),
            "sha256:" + "c" * 64,
        )
    ]
    retriever = HybridRetriever(chunks, "multilingual-char-ngram-v1")
    results = retriever.search(
        "flood evacuation", region="TH", language="en", hazard="FLOOD", at=now
    )
    assert results and results[0]["document_id"] == "doc-1"
    assert retriever.search("flood", region="US", language="en", hazard="FLOOD", at=now) == []
    with pytest.raises(ValueError, match="DENSE_ENCODER_NOT_APPROVED"):
        HybridRetriever(chunks, "unapproved-model")
    points = qdrant_points(chunks, dimensions=32)
    assert len(points[0]["vector"]) == 32
    evaluation = evaluate_retrieval(
        retriever,
        [
            {
                "name": "correct region",
                "query": "flood evacuation",
                "region": "TH",
                "language": "en",
                "hazard": "FLOOD",
                "expected_document_id": "doc-1",
            },
            {
                "name": "wrong region",
                "query": "flood",
                "region": "US",
                "language": "en",
                "hazard": "FLOOD",
                "expected_document_id": None,
            },
        ],
        at=now,
    )
    assert evaluation["passed"] is True


def test_override_is_monotonic_and_official_priority_wins(snapshot) -> None:
    assessment = assess_with_conservative_fallback(
        snapshot, [UUID(str(snapshot.route_candidates[0].route_id))]
    )[0]
    after = enforce_official_priority(assessment)
    validate_monotonic_override(assessment, after)
    weakened = assessment.model_copy(update={"risk_level": RiskLevel.LOW})
    with pytest.raises(ValueError, match="SAFETY_OVERRIDE_WEAKENED_RISK"):
        validate_monotonic_override(
            assessment.model_copy(update={"risk_level": RiskLevel.HIGH}), weakened
        )


def test_route_temporal_filter_and_snapshot_pipeline(snapshot) -> None:
    route = snapshot.route_candidates[0]
    outside = {
        "event_id": "old-closure",
        "official": True,
        "closure": True,
        "severity": "EXTREME",
        "geometry": route.geometry,
        "effective_at": "2020-01-01T00:00:00Z",
        "ends_at": "2020-01-01T01:00:00Z",
    }
    evaluated = evaluate_exposure(
        route,
        [outside],
        {"EXTREME": 1.0},
        starts_at=snapshot.travel_window.starts_at,
        ends_at=snapshot.travel_window.ends_at,
    )
    assert evaluated.exposure is not None and not evaluated.exposure.closed
    pipeline = evaluate_snapshot_routes(
        snapshot, [UUID(str(route.route_id))], severity_weights=None
    )
    assert pipeline[0].tradeoffs


@pytest.mark.asyncio
async def test_source_downloader_rejects_unapproved_url_without_network() -> None:
    with pytest.raises(ValueError, match="SOURCE_URL_NOT_ALLOWLISTED"):
        await download_approved_source({"source_url": "http://untrusted.invalid/a.pdf"}, set())
