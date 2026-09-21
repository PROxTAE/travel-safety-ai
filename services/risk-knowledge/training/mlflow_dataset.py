"""MLflow dataset tracking and metadata logger for Module 06.

Logs dataset manifests, checksums, distributions, and audit parameters to MLflow
using the MLflow 2.0 REST API with graceful fallback to local audit records
when the MLflow tracking service is offline.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
LOCAL_AUDIT_LOG_PATH = Path(__file__).resolve().parent / "data" / "mlflow_audit_log.json"


@dataclass(frozen=True)
class MLflowDatasetRecord:
    experiment_name: str
    run_name: str
    dataset_id: str
    content_checksum: str
    row_count: int
    class_distribution: dict[str, int]
    parameters: dict[str, str]
    metrics: dict[str, float]
    tags: dict[str, str]
    status: str
    run_id: str | None
    logged_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MLflowDatasetLogger:
    """Client for logging dataset metadata and checksums to MLflow via REST API."""

    def __init__(
        self,
        tracking_uri: str = DEFAULT_MLFLOW_URI,
        client: httpx.Client | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.tracking_uri = tracking_uri.rstrip("/")
        self._client = client
        self.timeout_seconds = timeout_seconds

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self.timeout_seconds)

    def log_dataset(
        self,
        manifest: dict[str, Any],
        bias_report: dict[str, Any],
        disagreement_report: dict[str, Any],
        experiment_name: str = "risk-knowledge-historical-dataset",
    ) -> MLflowDatasetRecord:
        """Log dataset parameters, metrics, tags, and manifest checksum to MLflow."""
        dataset_id = manifest["dataset_id"]
        run_name = f"dataset-{dataset_id}"
        now_iso = datetime.now(UTC).isoformat()

        # Build parameters
        parameters = {
            "dataset_id": dataset_id,
            "manifest_version": manifest["manifest_version"],
            "feature_schema_version": manifest["feature_schema_version"],
            "prediction_cutoff": manifest["prediction_cutoff"],
            "content_checksum": manifest["content_checksum"],
            "row_count": str(manifest["row_count"]),
            "split_method": manifest["split"]["method"],
            "random_seed": str(manifest["split"]["random_seed"]),
            "license_review": manifest["license_review"],
        }

        # Build metrics
        dist = manifest["class_distribution"]
        total = manifest["row_count"]
        metrics = {
            "class_count_low": float(dist.get("LOW", 0)),
            "class_count_medium": float(dist.get("MEDIUM", 0)),
            "class_count_high": float(dist.get("HIGH", 0)),
            "high_risk_ratio": float(dist.get("HIGH", 0)) / max(1.0, float(total)),
            "disagreement_rate": float(disagreement_report.get("disagreement_rate", 0.0)),
            "total_rows": float(total),
        }

        # Build tags
        tags = {
            "label_method": manifest["label_method"],
            "created_by": manifest["created_by"],
            "leakage_check_passed": str(manifest["split"]["leakage_check_passed"]).lower(),
            "source_count": str(len(manifest["sources"])),
        }

        # Attempt to log to remote MLflow server
        run_id = None
        status = "LOGGED_LOCAL_FALLBACK"

        client = self._get_client()
        try:
            # 1. Get or create experiment
            exp_resp = client.post(
                f"{self.tracking_uri}/api/2.0/mlflow/experiments/get-by-name",
                json={"experiment_name": experiment_name},
            )
            if exp_resp.status_code == 200:
                experiment_id = exp_resp.json()["experiment"]["experiment_id"]
            else:
                create_exp_resp = client.post(
                    f"{self.tracking_uri}/api/2.0/mlflow/experiments/create",
                    json={"name": experiment_name},
                )
                create_exp_resp.raise_for_status()
                experiment_id = create_exp_resp.json()["experiment_id"]

            # 2. Create run
            create_run_resp = client.post(
                f"{self.tracking_uri}/api/2.0/mlflow/runs/create",
                json={
                    "experiment_id": experiment_id,
                    "run_name": run_name,
                    "start_time": int(datetime.now(UTC).timestamp() * 1000),
                },
            )
            create_run_resp.raise_for_status()
            run_id = create_run_resp.json()["run"]["info"]["run_id"]

            # 3. Log parameters
            for k, v in parameters.items():
                client.post(
                    f"{self.tracking_uri}/api/2.0/mlflow/runs/log-parameter",
                    json={"run_id": run_id, "key": k, "value": v},
                )

            # 4. Log metrics
            for k, val in metrics.items():
                client.post(
                    f"{self.tracking_uri}/api/2.0/mlflow/runs/log-metric",
                    json={
                        "run_id": run_id,
                        "key": k,
                        "value": val,
                        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                    },
                )

            # 5. Log tags
            for k, v in tags.items():
                client.post(
                    f"{self.tracking_uri}/api/2.0/mlflow/runs/set-tag",
                    json={"run_id": run_id, "key": k, "value": v},
                )

            status = "LOGGED_MLFLOW_SERVER"
            logger.info(f"Successfully logged dataset to MLflow run {run_id}")
        except Exception as exc:
            logger.warning(
                f"MLflow tracking server unreachable at {self.tracking_uri} ({exc}); "
                "logging metadata to local audit log"
            )

        # Always record locally as well for offline audit and provenance
        record = MLflowDatasetRecord(
            experiment_name=experiment_name,
            run_name=run_name,
            dataset_id=dataset_id,
            content_checksum=manifest["content_checksum"],
            row_count=total,
            class_distribution=dist,
            parameters=parameters,
            metrics=metrics,
            tags=tags,
            status=status,
            run_id=run_id,
            logged_at=now_iso,
        )

        try:
            LOCAL_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            audit_entries = []
            if LOCAL_AUDIT_LOG_PATH.exists():
                try:
                    audit_entries = json.loads(LOCAL_AUDIT_LOG_PATH.read_text(encoding="utf-8"))
                except Exception:
                    audit_entries = []
            audit_entries.append(record.to_dict())
            LOCAL_AUDIT_LOG_PATH.write_text(
                json.dumps(audit_entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Failed to write local MLflow audit log: {e}")

        return record
