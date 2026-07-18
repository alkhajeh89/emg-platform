"""Confidence engine (FEAT-05-6, Deliverable 7).

Deterministic confidence scoring for nodes and edges. Rather than inventing a new
scoring model, this **wraps** `emg_trust_scoring.evaluate` — the platform's
existing deterministic trust engine — translating a memory-graph assertion's
evidence into `TrustSignals` and returning the composite score. This gives the
sprint's required behaviour for free and keeps a single scoring authority:

  * multiple independent evidence sources  → higher confidence
  * a single evidence source               → medium confidence
  * conflicting evidence                    → reduced confidence

The mapping and the band thresholds are configurable (`ConfidencePolicy`); the
underlying `ScoringPolicy` is reused unchanged, so trust-scoring remains the one
place scoring weights live. Pure and deterministic: identical inputs → identical
`ConfidenceAssessment`.
"""

from __future__ import annotations

from datetime import datetime

from emg_trust_scoring import (
    DEFAULT_POLICY,
    SOURCE_CONFIDENCE,
    ScoringPolicy,
    TrustSignals,
    evaluate,
)
from emg_trust_scoring.result import TrustScoreResult
from pydantic import BaseModel, ConfigDict, Field

from .enums import ConfidenceBand, EvidenceSource
from .evidence import EvidenceRef

# Map each evidence source to the trust engine's coarse source_type vocabulary
# ("system" | "api" | "document" | "human" | "ai"). Documents and messaging
# systems are "document"; a hand-entered fact is "human".
_SOURCE_TYPE: dict[EvidenceSource, str] = {
    EvidenceSource.EMAIL: "document",
    EvidenceSource.MEETING_MINUTES: "document",
    EvidenceSource.PDF: "document",
    EvidenceSource.WORD_DOCUMENT: "document",
    EvidenceSource.SHAREPOINT: "document",
    EvidenceSource.TEAMS: "document",
    EvidenceSource.JIRA: "api",
    EvidenceSource.MANUAL_ENTRY: "human",
}


class ConfidencePolicy(BaseModel):
    """Immutable confidence policy: the trust `ScoringPolicy` plus band cutoffs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scoring_policy: ScoringPolicy = DEFAULT_POLICY
    high_band: float = Field(default=0.75, ge=0.0, le=1.0)
    medium_band: float = Field(default=0.5, ge=0.0, le=1.0)


class ConfidenceAssessment(BaseModel):
    """The immutable, deterministic result of scoring one assertion's evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    band: ConfidenceBand
    evidence_count: int = Field(ge=0)
    distinct_source_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    explanation: str
    trust: TrustScoreResult


def _dominant_source_type(evidence: tuple[EvidenceRef, ...]) -> str:
    """Pick the most authoritative source type present (highest SOURCE_CONFIDENCE),
    deterministically. Empty → 'document' (a neutral default)."""
    if not evidence:
        return "document"
    types = {_SOURCE_TYPE[e.source] for e in evidence}
    return max(sorted(types), key=lambda t: SOURCE_CONFIDENCE.get(t, 0.0))


class ConfidenceEngine:
    """Deterministic confidence scorer over evidence sets."""

    def __init__(self, policy: ConfidencePolicy | None = None) -> None:
        self._policy = policy or ConfidencePolicy()

    @property
    def policy(self) -> ConfidencePolicy:
        return self._policy

    def _band(self, score: float, conflict_count: int, evidence_count: int) -> ConfidenceBand:
        # Conflicts that outweigh corroboration dominate the band.
        if conflict_count > 0 and conflict_count * 2 >= max(evidence_count, 1):
            return ConfidenceBand.CONFLICTED
        if score >= self._policy.high_band:
            return ConfidenceBand.HIGH
        if score >= self._policy.medium_band:
            return ConfidenceBand.MEDIUM
        return ConfidenceBand.LOW

    def assess(
        self,
        evidence: tuple[EvidenceRef, ...],
        *,
        as_of: datetime,
        conflict_count: int = 0,
    ) -> ConfidenceAssessment:
        """Score an assertion from its evidence. `conflict_count` is the number of
        evidence items that contradict the assertion (reduces confidence)."""
        distinct_sources = len({e.source for e in evidence})
        signals = TrustSignals(
            as_of=as_of,
            source_type=_dominant_source_type(evidence),  # type: ignore[arg-type]
            provenance_present=len(evidence) > 0,
            provenance_has_audit_event=any(e.event_id for e in evidence),
            provenance_has_correlation=any(e.correlation_id for e in evidence),
            provenance_link_count=min(
                3, sum(1 for e in evidence if e.event_id or e.correlation_id)
            ),
            evidence_expected=max(1, distinct_sources),
            evidence_present=distinct_sources,
            evidence_conflicts=conflict_count,
            effective_from=as_of,
        )
        trust = evaluate(signals, self._policy.scoring_policy).trust
        band = self._band(trust.score, conflict_count, len(evidence))
        explanation = (
            f"{len(evidence)} evidence item(s) across {distinct_sources} distinct "
            f"source(s); {conflict_count} conflict(s); dominant source_type="
            f"{signals.source_type}; composite={trust.score:.4f} -> {band.value}"
        )
        return ConfidenceAssessment(
            score=trust.score,
            band=band,
            evidence_count=len(evidence),
            distinct_source_count=distinct_sources,
            conflict_count=conflict_count,
            explanation=explanation,
            trust=trust,
        )
