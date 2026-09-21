"""Quality gates retain explicit unknown, stale, and conflicting evidence.

The route quality in the #46 regression case is the module 04 openrouteservice
record from tests/fixtures/m04-route-candidates.json; other qualities are
hand-built so each dimension has a hand-computed expected score.
"""

import json
from pathlib import Path

import pytest

from app.domain.canonical import DataQuality, QualityConflict
from app.pipeline.quality import (
    SCORE_VERSION,
    QualityDimensions,
    QualityPolicy,
    measure_dimensions,
    summarize_quality,
    weighted_score,
)

POLICY = QualityPolicy("review-1", 0.8, 0.7)
FULL = QualityDimensions(1.0, 1.0, 1.0, 1.0, 1.0)


def quality(
    *,
    status: str = "FRESH",
    coverage: float | None = 0.9,
    completeness: float | None = 1.0,
    freshness_seconds: int | None = 60,
    conflicts: list[QualityConflict] | None = None,
) -> DataQuality:
    return DataQuality(
        status=status,
        coverage=coverage,
        completeness=completeness,
        freshness_seconds=freshness_seconds,
        conflicts=conflicts or [],
    )


def summarize(
    sources: dict[str, DataQuality],
    *,
    dimensions: QualityDimensions = FULL,
    identity_valid: bool = True,
    geometry_valid: bool = True,
):
    return summarize_quality(
        sources,
        required=frozenset({"weather", "route"}),
        dimensions=dimensions,
        policy=POLICY,
        identity_valid=identity_valid,
        geometry_valid=geometry_valid,
    )


def test_required_evidence_and_invalid_identity_block() -> None:
    missing = summarize({"weather": quality()})
    assert missing.gate == "BLOCK"
    assert missing.missing_critical == ("route",)
    assert "MISSING" in missing.flags
    invalid = summarize({"weather": quality(), "route": quality()}, identity_valid=False)
    assert invalid.gate == "BLOCK"


def test_unknown_dimension_or_stale_source_degrades() -> None:
    unknown = summarize(
        {"weather": quality(), "route": quality()},
        dimensions=QualityDimensions(1.0, 1.0, 1.0, None, 1.0),
    )
    assert unknown.gate == "DEGRADED"
    assert unknown.score is None
    assert "INCOMPLETE" in unknown.flags
    stale = summarize({"weather": quality(status="STALE"), "route": quality()})
    assert stale.gate == "DEGRADED"
    assert "STALE" in stale.flags


def test_conflict_preserved_and_clean_sources_pass() -> None:
    sources = {"weather": quality(), "route": quality()}
    clean = summarize(sources)
    assert clean.gate == "PASS"
    assert clean.score == 1.0
    assert clean.score_version == SCORE_VERSION
    sources["weather"] = quality(
        status="CONFLICTING",
        conflicts=[
            QualityConflict(
                field_path="severity",
                source_ids=["usgs:captured-event", "official:conflicting-event"],
                resolution="UNRESOLVED",
            )
        ],
    )
    result = summarize(sources)
    assert result.gate == "DEGRADED"
    assert result.conflict_count == 1
    assert "CONFLICTING" in result.flags


def test_weighted_score_matches_hand_computed_value() -> None:
    # 0.25*0.8 + 0.20*0.5 + 0.25*0.6 + 0.15*1.0 + 0.15*0.7 = 0.705
    assert weighted_score(QualityDimensions(0.8, 0.5, 0.6, 1.0, 0.7)) == 0.705


def test_score_rounds_half_even_at_four_places() -> None:
    # 0.25 * 0.0002 = 0.00005 is a tie; half-even keeps 0.0000 where half-up gives 0.0001.
    assert weighted_score(QualityDimensions(0.0002, 0.0, 0.0, 0.0, 0.0)) == 0.0
    # 0.25 * 0.0006 = 0.00015 is a tie; half-even goes to the even 0.0002.
    assert weighted_score(QualityDimensions(0.0006, 0.0, 0.0, 0.0, 0.0)) == 0.0002


def test_high_score_cannot_overrule_invalid_geometry() -> None:
    result = summarize({"weather": quality(), "route": quality()}, geometry_valid=False)
    assert result.score == 1.0
    assert result.gate == "BLOCK"


def test_old_road_graph_marked_fresh_is_not_stale() -> None:
    """Issue #46: an eight-day-old road graph is FRESH by the producer's own rule."""
    route = json.loads(
        (Path(__file__).parent / "fixtures" / "m04-route-candidates.json").read_text(
            encoding="utf-8"
        )
    )["records"][0]["quality"]
    route_quality = DataQuality.model_validate(route | {"flags": []})
    assert route_quality.freshness_seconds == 689760
    result = summarize({"weather": quality(), "route": route_quality})
    assert "STALE" not in result.flags


def test_measured_dimensions_keep_unknowns_unknown() -> None:
    sources = {"weather": quality(completeness=0.5), "route": quality(status="STALE")}
    dims = measure_dimensions(
        sources,
        required=frozenset({"weather", "route"}),
        coverage=0.75,
        comparable_facts=4,
        unresolved_conflicts=1,
        authorities=["OFFICIAL", "LICENSED_PROVIDER"],
    )
    assert dims.freshness == 0.5
    assert dims.completeness == 0.5
    assert dims.coverage == 0.75
    assert dims.agreement == 0.75
    assert dims.authority == pytest.approx(0.85)
    single = measure_dimensions(
        sources,
        required=frozenset({"weather", "route", "transport"}),
        coverage=None,
        comparable_facts=0,
        unresolved_conflicts=0,
        authorities=["OFFICIAL", "UNKNOWN"],
    )
    assert single == QualityDimensions(None, None, None, None, None)


def test_conflicts_cannot_exceed_comparable_facts() -> None:
    with pytest.raises(ValueError):
        measure_dimensions(
            {},
            required=frozenset(),
            coverage=None,
            comparable_facts=1,
            unresolved_conflicts=2,
            authorities=[],
        )


def test_cross_source_conflict_flags_and_degrades() -> None:
    result = summarize_quality(
        {"weather": quality(), "route": quality()},
        required=frozenset({"weather", "route"}),
        dimensions=FULL,
        policy=POLICY,
        identity_valid=True,
        geometry_valid=True,
        unresolved_conflicts=1,
    )
    assert result.conflict_count == 1
    assert "CONFLICTING" in result.flags
    assert result.gate == "DEGRADED"
