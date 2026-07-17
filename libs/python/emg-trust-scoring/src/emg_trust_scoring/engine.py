"""The deterministic trust-scoring engine (FEAT-05-3).

Pure functions only: identical `TrustSignals` + `ScoringPolicy` always yield an
identical, byte-reproducible `TrustScoreResult`. No wall-clock reads (temporal
decay uses `signals.as_of`), no randomness, no I/O, no global state. Every factor
is clamped to ``[0, 1]`` and the composite is a weighted average of the factor
sub-scores, so a single manipulated signal can never push a factor above its
clamp or dominate the score.

Trust is **calculated** from the observable signals; there is no code path by
which a caller supplies a trust value directly.
"""

from __future__ import annotations

from .factors import ALL_FACTORS, TrustFactor
from .policy import DEFAULT_POLICY, SOURCE_CONFIDENCE, ScoringPolicy
from .result import FactorContribution, TrustScoreResult
from .signals import TrustSignals


def _clamp(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _source_confidence(s: TrustSignals) -> float:
    return SOURCE_CONFIDENCE.get(s.source_type, 0.0)


def _provenance_quality(s: TrustSignals) -> float:
    if not s.provenance_present:
        return 0.0
    quality = 0.4  # provenance is present at all
    if s.provenance_has_audit_event:
        quality += 0.3
    if s.provenance_has_correlation:
        quality += 0.1
    quality += 0.2 * (s.provenance_link_count / 3.0)
    return _clamp(quality)


def _evidence_completeness(s: TrustSignals) -> float:
    # Nothing required => complete by default; else the present/expected ratio.
    base = 1.0 if s.evidence_expected == 0 else min(s.evidence_present / s.evidence_expected, 1.0)
    if s.evidence_conflicts > 0:
        if s.evidence_present > 0:
            base *= max(0.0, 1.0 - (s.evidence_conflicts / s.evidence_present))
        else:
            base = 0.0  # conflicts with no supporting evidence
    return _clamp(base)


def _validation_status(s: TrustSignals) -> float:
    if not s.ontology_conformant:
        return 0.0
    return _clamp(1.0 - 0.25 * s.validation_error_count - 0.05 * s.validation_warning_count)


def _ownership_confidence(s: TrustSignals) -> float:
    if not s.owner_present:
        return 0.0
    return 1.0 if s.owner_registered else 0.6


def _temporal_freshness(s: TrustSignals, policy: ScoringPolicy) -> float:
    # A superseded/retired record, or one past its effective window, is no longer
    # current knowledge -> zero freshness.
    if s.lifecycle_status in ("superseded", "retired"):
        return 0.0
    if s.effective_to is not None and s.as_of >= s.effective_to:
        return 0.0
    age_days = max(0.0, (s.as_of - s.effective_from).total_seconds() / 86400.0)
    return _clamp(0.5 ** (age_days / policy.half_life_days))


def _relationship_consistency(s: TrustSignals) -> float:
    if s.relationship_total == 0:
        return 1.0  # no relationships => nothing inconsistent
    return _clamp(1.0 - s.relationship_conflicts / s.relationship_total)


def _ingestion_quality(s: TrustSignals) -> float:
    # Redactions are a minor signal (secrets stripped); a bound violation is
    # severe (should never have been ingested).
    return _clamp(1.0 - 0.1 * s.ingestion_redactions - 0.5 * s.ingestion_bound_violations)


def compute_factor_scores(
    signals: TrustSignals, policy: ScoringPolicy = DEFAULT_POLICY
) -> dict[TrustFactor, float]:
    """The per-factor normalized sub-scores (each in ``[0, 1]``), rounded to the
    policy precision for reproducibility."""
    raw: dict[TrustFactor, float] = {
        TrustFactor.SOURCE_CONFIDENCE: _source_confidence(signals),
        TrustFactor.PROVENANCE_QUALITY: _provenance_quality(signals),
        TrustFactor.EVIDENCE_COMPLETENESS: _evidence_completeness(signals),
        TrustFactor.VALIDATION_STATUS: _validation_status(signals),
        TrustFactor.OWNERSHIP_CONFIDENCE: _ownership_confidence(signals),
        TrustFactor.TEMPORAL_FRESHNESS: _temporal_freshness(signals, policy),
        TrustFactor.RELATIONSHIP_CONSISTENCY: _relationship_consistency(signals),
        TrustFactor.INGESTION_QUALITY: _ingestion_quality(signals),
    }
    return {f: round(_clamp(raw[f]), policy.precision) for f in ALL_FACTORS}


def evaluate_trust(
    signals: TrustSignals, policy: ScoringPolicy = DEFAULT_POLICY
) -> TrustScoreResult:
    """Compute the immutable composite trust score with a per-factor breakdown
    and explanation."""
    factor_scores = compute_factor_scores(signals, policy)
    breakdown: list[FactorContribution] = []
    for factor in ALL_FACTORS:
        raw_score = factor_scores[factor]
        weight = round(policy.weights[factor], policy.precision)
        contribution = round(weight * raw_score, policy.precision)
        breakdown.append(
            FactorContribution(
                factor=factor, raw_score=raw_score, weight=weight, contribution=contribution
            )
        )
    score = round(_clamp(sum(item.contribution for item in breakdown)), policy.precision)
    accepted = score >= policy.acceptance_threshold
    explanation = _explain(score, accepted, policy, breakdown)
    return TrustScoreResult(
        score=score,
        accepted=accepted,
        policy_version=policy.policy_version,
        breakdown=tuple(breakdown),
        explanation=explanation,
    )


def _explain(
    score: float,
    accepted: bool,
    policy: ScoringPolicy,
    breakdown: list[FactorContribution],
) -> str:
    verdict = "accepted" if accepted else "below threshold"
    parts = [
        f"trust={score:.{policy.precision}f} ({verdict} @ {policy.acceptance_threshold:g}, "
        f"policy v{policy.policy_version})"
    ]
    for item in breakdown:
        parts.append(
            f"  {item.factor.value}: raw={item.raw_score:g} "
            f"weight={item.weight:g} -> {item.contribution:g}"
        )
    return "\n".join(parts)
