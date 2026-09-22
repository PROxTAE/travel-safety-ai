"""Shared "is the evidence package good enough" predicate.

Used by both `validate_evidence` (`app/graph/nodes/validate_evidence.py`, which increments the
retry counter) and its routing decision (`app/graph/routing.build_after_validate_evidence`, which
enforces the retry limit) so the two can never silently drift out of agreement about what counts
as insufficient.
"""

from __future__ import annotations

from app.graph.state import DataStatus, QualityFlag, QualitySection

_INSUFFICIENT_FLAGS = frozenset({QualityFlag.MISSING, QualityFlag.INCOMPLETE})


def evidence_insufficient(quality: QualitySection) -> bool:
    return quality.freshness is not DataStatus.FRESH or bool(
        _INSUFFICIENT_FLAGS.intersection(quality.quality_flags)
    )
