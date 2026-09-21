"""Versioned, deterministic quality aggregation for integrated evidence."""

from collections.abc import Iterable
from dataclasses import dataclass, fields
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from app.domain.canonical import DataQuality

Gate = Literal["PASS", "DEGRADED", "BLOCK"]
Authority = Literal["OFFICIAL", "INTERGOVERNMENTAL", "LICENSED_PROVIDER", "COMMUNITY", "UNKNOWN"]

# Proposal from docs/quality-gate.md; modules 03 and 07 must approve before PASS is relied on.
SCORE_VERSION = "quality.integrated/0.1.0"
WEIGHTS = {
    "freshness": Decimal("0.25"),
    "completeness": Decimal("0.20"),
    "coverage": Decimal("0.25"),
    "agreement": Decimal("0.15"),
    "authority": Decimal("0.15"),
}
AUTHORITY_SCALE_VERSION = "authority.scale/0.1.0"
AUTHORITY_SCALE = {
    "OFFICIAL": 1.0,
    "INTERGOVERNMENTAL": 0.9,
    "LICENSED_PROVIDER": 0.7,
    "COMMUNITY": 0.4,
}
UNUSABLE = {"STALE", "UNAVAILABLE"}


@dataclass(frozen=True)
class QualityPolicy:
    version: str
    minimum_coverage: float
    minimum_score: float

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("quality policy version required")
        if not (0 <= self.minimum_coverage <= 1 and 0 <= self.minimum_score <= 1):
            raise ValueError("quality thresholds must be within [0, 1]")


@dataclass(frozen=True)
class QualityDimensions:
    """Each value is in [0, 1]; None means the dimension could not be measured."""

    freshness: float | None
    completeness: float | None
    coverage: float | None
    agreement: float | None
    authority: float | None

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{field.name} must be within [0, 1]")


@dataclass(frozen=True)
class QualitySummary:
    policy_version: str
    score_version: str
    gate: Gate
    score: float | None
    coverage: float | None
    flags: tuple[str, ...]
    missing_critical: tuple[str, ...]
    conflict_count: int
    source_count: int


def measure_dimensions(
    sources: dict[str, DataQuality],
    *,
    required: frozenset[str],
    coverage: float | None,
    comparable_facts: int,
    unresolved_conflicts: int,
    authorities: Iterable[Authority],
) -> QualityDimensions:
    """Measure the five proposal dimensions without inventing any unknown input."""
    if comparable_facts < 0 or not 0 <= unresolved_conflicts <= max(comparable_facts, 0):
        raise ValueError("conflicts must be within the comparable fact count")
    present = [sources[name] for name in sorted(required) if name in sources]
    measured = len(present) == len(required) and bool(required)
    freshness = sum(q.status not in UNUSABLE for q in present) / len(present) if measured else None
    completeness_values = [q.completeness for q in present]
    completeness = (
        min(v for v in completeness_values if v is not None)
        if measured and None not in completeness_values
        else None
    )
    # A single source has nothing to agree with, so agreement stays unknown.
    agreement = 1 - unresolved_conflicts / comparable_facts if comparable_facts else None
    ranks = list(authorities)
    authority = (
        sum(AUTHORITY_SCALE[rank] for rank in ranks) / len(ranks)
        if ranks and "UNKNOWN" not in ranks
        else None
    )
    return QualityDimensions(freshness, completeness, coverage, agreement, authority)


def weighted_score(dimensions: QualityDimensions) -> float | None:
    """Weighted sum rounded half-even to four places; any unknown dimension gives None."""
    total = Decimal(0)
    for name, weight in WEIGHTS.items():
        value = getattr(dimensions, name)
        if value is None:
            return None
        total += weight * Decimal(str(value))
    return float(total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))


def summarize_quality(
    sources: dict[str, DataQuality],
    *,
    required: frozenset[str],
    dimensions: QualityDimensions,
    policy: QualityPolicy,
    identity_valid: bool,
    geometry_valid: bool,
    unresolved_conflicts: int = 0,
) -> QualitySummary:
    """Keep missing evidence visible; a high score never overrules a blocking condition.

    `unresolved_conflicts` counts disagreements found across sources (for example by
    dedup), which no single producer's DataQuality can report.
    """
    missing = tuple(
        sorted(
            name
            for name in required
            if name not in sources or sources[name].status == "UNAVAILABLE"
        )
    )
    flags = {flag for quality in sources.values() for flag in quality.flags}
    if missing:
        flags.add("MISSING")
    if unresolved_conflicts < 0:
        raise ValueError("unresolved conflicts must be nonnegative")
    conflict_count = unresolved_conflicts + sum(len(q.conflicts) for q in sources.values())
    if conflict_count or any(q.status == "CONFLICTING" for q in sources.values()):
        flags.add("CONFLICTING")
    # Producers judge staleness per source; a road graph and a realtime feed age differently.
    if any(q.status == "STALE" for q in sources.values()):
        flags.add("STALE")
    score = weighted_score(dimensions)
    if score is None:
        flags.add("INCOMPLETE")
    coverage = dimensions.coverage
    if not identity_valid or not geometry_valid or missing:
        gate: Gate = "BLOCK"
    elif (
        score is None
        or coverage is None
        or score < policy.minimum_score
        or coverage < policy.minimum_coverage
        or flags
        or any(q.status != "FRESH" for q in sources.values())
    ):
        gate = "DEGRADED"
    else:
        gate = "PASS"
    return QualitySummary(
        policy.version,
        SCORE_VERSION,
        gate,
        score,
        coverage,
        tuple(sorted(flags)),
        missing,
        conflict_count,
        len(sources),
    )
