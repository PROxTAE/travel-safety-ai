"""Canonical value objects that every module-04 record carries.

Shapes follow 00_API_AND_DATA_CONTRACTS.md § 3.3 and § 3.4 exactly. The record
types themselves (WeatherForecastPoint, DisasterEvent, ...) arrive in Phase 2-5;
these two are the part every phase depends on.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import DataStatus, QualityFlag, SourceAuthority

SCHEMA_VERSION = "1.0.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


def content_hash(payload: Any) -> str:
    """sha256 over a stable JSON rendering, for dedup and audit."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


class SourceProvenance(BaseModel):
    """Where a fact came from. Required on every record that reaches a consumer."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    provider: str
    provider_record_id: str | None = None
    authority: SourceAuthority
    source_url: str | None = None
    license: str | None = None

    # The provider's own observation time. None when the provider does not supply
    # one -- model output such as a weather forecast never has one. Substituting
    # fetched_at here would present a prediction as a measurement.
    observed_at: datetime | None = None
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None

    content_hash: str | None = None
    schema_version: str = SCHEMA_VERSION

    @model_validator(mode="after")
    def _reject_fetched_as_observed(self) -> Self:
        if self.observed_at is not None and self.observed_at == self.fetched_at:
            raise ValueError(
                "observed_at must not be copied from fetched_at; use None plus a "
                "quality flag when the provider gives no observation time"
            )
        return self


class DataQuality(BaseModel):
    """How much this record can be trusted. Flags are never hidden behind score."""

    model_config = ConfigDict(extra="forbid")

    status: DataStatus
    # Left None until the weighted formula is agreed with module 05 (open
    # question Q5). A placeholder number here would be worse than no number.
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    score_version: str | None = None
    flags: list[QualityFlag] = Field(default_factory=list)
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    completeness: float | None = Field(default=None, ge=0.0, le=1.0)
    freshness_seconds: int | None = Field(default=None, ge=0)
    conflicts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _score_needs_version(self) -> Self:
        if self.score is not None and not self.score_version:
            raise ValueError("score requires score_version")
        return self

    @classmethod
    def from_age(
        cls,
        *,
        age_seconds: int,
        fresh_within_seconds: int,
        flags: list[QualityFlag] | None = None,
        notes: list[str] | None = None,
    ) -> DataQuality:
        """Derive FRESH/STALE from the shared freshness table."""
        stale = age_seconds > fresh_within_seconds
        resolved = list(flags or [])
        if stale and QualityFlag.STALE not in resolved:
            resolved.append(QualityFlag.STALE)
        return cls(
            status=DataStatus.STALE if stale else DataStatus.FRESH,
            flags=resolved,
            freshness_seconds=age_seconds,
            notes=list(notes or []),
        )

    @classmethod
    def unavailable(cls, reason: str) -> DataQuality:
        return cls(
            status=DataStatus.UNAVAILABLE,
            flags=[QualityFlag.MISSING],
            notes=[reason],
        )
