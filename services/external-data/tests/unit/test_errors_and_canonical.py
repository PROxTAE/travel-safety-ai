"""Error mapping and the two value objects every record carries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain.canonical import DataQuality, SourceProvenance, content_hash
from app.domain.enums import DataStatus, QualityFlag, SourceAuthority
from app.domain.errors import (
    ApiErrorCode,
    ProviderError,
    ProviderErrorCode,
    map_provider_error,
)


@pytest.mark.parametrize("code", list(ProviderErrorCode))
def test_every_provider_code_maps_to_an_api_code(code: ProviderErrorCode) -> None:
    api_code, status, message, _ = map_provider_error(
        ProviderError(code, "some_provider")
    )
    assert isinstance(api_code, ApiErrorCode)
    assert 400 <= status < 600
    assert message


@pytest.mark.parametrize("code", list(ProviderErrorCode))
def test_safe_message_never_names_the_provider(code: ProviderErrorCode) -> None:
    """A consumer must not learn which upstream failed, or that our key is bad."""
    _, _, message, _ = map_provider_error(
        ProviderError(code, "openrouteservice", message="Invalid API key abc123")
    )
    lowered = message.lower()
    assert "openrouteservice" not in lowered
    assert "abc123" not in lowered
    assert "api key" not in lowered


def test_coverage_failures_are_not_retryable() -> None:
    for code in (
        ProviderErrorCode.OUTSIDE_COVERAGE,
        ProviderErrorCode.LICENSE_RESTRICTION,
        ProviderErrorCode.PROVIDER_AUTH,
    ):
        _, _, _, retryable = map_provider_error(ProviderError(code, "p"))
        assert retryable is False


def test_rate_limit_maps_to_429_and_is_retryable() -> None:
    api_code, status, _, retryable = map_provider_error(
        ProviderError(ProviderErrorCode.PROVIDER_RATE_LIMIT, "p")
    )
    assert api_code is ApiErrorCode.RATE_LIMITED
    assert status == 429
    assert retryable is True


def test_outside_coverage_maps_to_unsupported_coverage() -> None:
    api_code, status, _, _ = map_provider_error(
        ProviderError(ProviderErrorCode.OUTSIDE_COVERAGE, "p")
    )
    assert api_code is ApiErrorCode.UNSUPPORTED_COVERAGE
    assert status == 422


# ------------------------------------------------------------------ provenance


def test_provenance_rejects_fetched_at_posing_as_observed_at() -> None:
    """The contract calls this out explicitly: passing off a fetch time as an
    observation time makes model output look like a measurement."""
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        SourceProvenance(
            source_id="x",
            provider="open_meteo_forecast",
            authority=SourceAuthority.LICENSED_PROVIDER,
            observed_at=now,
            fetched_at=now,
        )


def test_provenance_allows_null_observed_at() -> None:
    provenance = SourceProvenance(
        source_id="x",
        provider="open_meteo_forecast",
        authority=SourceAuthority.LICENSED_PROVIDER,
        observed_at=None,
    )
    assert provenance.observed_at is None
    assert provenance.schema_version == "1.0.0"


def test_provenance_accepts_a_real_observation_time() -> None:
    fetched = datetime.now(UTC)
    provenance = SourceProvenance(
        source_id="usgs:abc",
        provider="usgs_earthquake",
        authority=SourceAuthority.OFFICIAL,
        observed_at=fetched - timedelta(minutes=4),
        fetched_at=fetched,
    )
    assert provenance.observed_at < provenance.fetched_at


def test_content_hash_is_order_independent() -> None:
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


# --------------------------------------------------------------------- quality


def test_score_requires_a_version() -> None:
    with pytest.raises(ValidationError):
        DataQuality(status=DataStatus.FRESH, score=0.9)


def test_score_with_version_is_accepted() -> None:
    quality = DataQuality(status=DataStatus.FRESH, score=0.9, score_version="v1")
    assert quality.score == 0.9


def test_score_is_none_by_default() -> None:
    """Q5 is unanswered, so no placeholder number is invented."""
    assert DataQuality(status=DataStatus.FRESH).score is None


def test_from_age_marks_stale_past_the_threshold() -> None:
    quality = DataQuality.from_age(age_seconds=4000, fresh_within_seconds=3600)
    assert quality.status is DataStatus.STALE
    assert QualityFlag.STALE in quality.flags
    assert quality.freshness_seconds == 4000


def test_from_age_stays_fresh_inside_the_threshold() -> None:
    quality = DataQuality.from_age(age_seconds=120, fresh_within_seconds=900)
    assert quality.status is DataStatus.FRESH
    assert QualityFlag.STALE not in quality.flags


def test_unavailable_carries_a_reason() -> None:
    quality = DataQuality.unavailable("provider not configured")
    assert quality.status is DataStatus.UNAVAILABLE
    assert quality.notes == ["provider not configured"]
