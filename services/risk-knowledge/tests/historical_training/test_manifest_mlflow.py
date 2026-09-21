"""Unit tests for dataset manifest validation and MLflow logging."""

from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from training.build_dataset import run_pipeline
from training.manifest import (
    build_dataset_manifest,
    compute_dataset_content_checksum,
    load_manifest_schema,
    validate_manifest,
)
from training.mlflow_dataset import MLflowDatasetLogger


def test_manifest_schema_compiles() -> None:
    schema = load_manifest_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "required" in schema
    assert "content_checksum" in schema["required"]


def test_build_valid_manifest() -> None:
    manifest = build_dataset_manifest(
        dataset_id="test-dataset-01",
        prediction_cutoff="2024-06-01T00:00:00Z",
        label_method="MIXED",
        sources=[
            {
                "name": "USGS Earthquake API",
                "source_url": "https://earthquake.usgs.gov/fdsnws/event/1/query",
                "authority": "OFFICIAL",
                "license": "Public Domain",
                "retrieved_at": "2024-06-01T00:00:00Z",
                "query_checksum": "sha256:" + "a" * 64,
            }
        ],
        query_windows=[{"source": "USGS", "start": "2024-01-01"}],
        split_info={
            "method": "TIME_AND_GEOGRAPHY_GROUPED",
            "time_boundaries": {"train": {"start": "2024-01-01", "end": "2024-03-01"}},
            "geography_groups": ["NORTH_CORRIDOR", "SOUTH_CORRIDOR"],
            "random_seed": 42,
            "leakage_check_passed": True,
        },
        row_count=10,
        class_distribution={"LOW": 6, "MEDIUM": 2, "HIGH": 2},
        content_checksum="sha256:" + "b" * 64,
        license_review="APPROVED",
        created_by="module-06-tester",
    )
    assert manifest["manifest_version"] == "1.0.0"
    validate_manifest(manifest)


def test_manifest_rejects_invalid_checksum() -> None:
    with pytest.raises(ValidationError):
        build_dataset_manifest(
            dataset_id="test-dataset-02",
            prediction_cutoff="2024-06-01T00:00:00Z",
            label_method="OFFICIAL_ALERT",
            sources=[
                {
                    "name": "USGS",
                    "source_url": "https://earthquake.usgs.gov/fdsnws/event/1/query",
                    "authority": "OFFICIAL",
                    "license": "Public Domain",
                    "retrieved_at": "2024-06-01T00:00:00Z",
                    "query_checksum": "invalid-no-sha256",  # invalid pattern
                }
            ],
            query_windows=[],
            split_info={
                "method": "TIME_AND_GEOGRAPHY_GROUPED",
                "time_boundaries": {},
                "geography_groups": ["G1", "G2"],
                "random_seed": 42,
                "leakage_check_passed": True,
            },
            row_count=1,
            class_distribution={"LOW": 1},
            content_checksum="invalid",
        )


def test_content_checksum_determinism() -> None:
    rows = [{"id": 1, "val": "abc"}, {"id": 2, "val": "def"}]
    ck1 = compute_dataset_content_checksum(rows)
    ck2 = compute_dataset_content_checksum(rows)
    assert ck1 == ck2
    assert ck1.startswith("sha256:")
    assert len(ck1) == 7 + 64


def test_mlflow_dataset_logger_local_fallback(tmp_path: Path) -> None:
    logger = MLflowDatasetLogger(tracking_uri="http://127.0.0.1:59999")  # unreachable port
    manifest = {
        "dataset_id": "test-offline-dataset",
        "manifest_version": "1.0.0",
        "feature_schema_version": "1.0.0",
        "prediction_cutoff": "2024-06-01T00:00:00Z",
        "content_checksum": "sha256:" + "c" * 64,
        "row_count": 50,
        "label_method": "MIXED",
        "sources": [{"name": "USGS"}],
        "created_by": "tester",
        "license_review": "APPROVED",
        "class_distribution": {"LOW": 30, "MEDIUM": 10, "HIGH": 10},
        "split": {
            "method": "TIME_AND_GEOGRAPHY_GROUPED",
            "random_seed": 42,
            "leakage_check_passed": True,
        },
    }
    rec = logger.log_dataset(
        manifest=manifest,
        bias_report={},
        disagreement_report={"disagreement_rate": 0.05},
    )
    assert rec.status == "LOGGED_LOCAL_FALLBACK"
    assert rec.dataset_id == "test-offline-dataset"
    assert rec.row_count == 50


def test_end_to_end_pipeline_and_reproducibility(tmp_path: Path) -> None:
    res1 = run_pipeline(
        dataset_id="test-reproducible-v1",
        prediction_cutoff="2024-06-01T00:00:00Z",
        output_dir=tmp_path / "run1",
    )
    res2 = run_pipeline(
        dataset_id="test-reproducible-v1",
        prediction_cutoff="2024-06-01T00:00:00Z",
        output_dir=tmp_path / "run2",
    )
    # Bit-for-bit identical content checksum
    assert res1["content_checksum"] == res2["content_checksum"]
    assert res1["manifest"]["row_count"] == res2["manifest"]["row_count"]
    assert res1["manifest"]["row_count"] > 0
    assert res1["bias_report"]["bias_checks"]["high_risk_represented"] is True
