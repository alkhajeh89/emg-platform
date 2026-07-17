"""Trust factors (Module 7 — Knowledge Graph, EPIC-05, FEAT-05-3).

The eight dimensions the composite confidence (trust) score is built from. Each
factor is computed deterministically to a normalized sub-score in ``[0.0, 1.0]``
from the observable `TrustSignals`, then combined under the `ScoringPolicy`
weights. Trust is therefore *calculated* from evidence about a record — never a
value a caller supplies.
"""

from __future__ import annotations

from enum import Enum


class TrustFactor(str, Enum):
    """A named trust dimension. The string values are stable identifiers used in
    the policy weights, the scoring breakdown, and the deterministic descriptor
    (so a golden test can pin the factor set)."""

    SOURCE_CONFIDENCE = "source_confidence"
    PROVENANCE_QUALITY = "provenance_quality"
    EVIDENCE_COMPLETENESS = "evidence_completeness"
    VALIDATION_STATUS = "validation_status"
    OWNERSHIP_CONFIDENCE = "ownership_confidence"
    TEMPORAL_FRESHNESS = "temporal_freshness"
    RELATIONSHIP_CONSISTENCY = "relationship_consistency"
    INGESTION_QUALITY = "ingestion_quality"


# Canonical, stable ordering for deterministic iteration / breakdown / descriptor.
ALL_FACTORS: tuple[TrustFactor, ...] = (
    TrustFactor.SOURCE_CONFIDENCE,
    TrustFactor.PROVENANCE_QUALITY,
    TrustFactor.EVIDENCE_COMPLETENESS,
    TrustFactor.VALIDATION_STATUS,
    TrustFactor.OWNERSHIP_CONFIDENCE,
    TrustFactor.TEMPORAL_FRESHNESS,
    TrustFactor.RELATIONSHIP_CONSISTENCY,
    TrustFactor.INGESTION_QUALITY,
)
