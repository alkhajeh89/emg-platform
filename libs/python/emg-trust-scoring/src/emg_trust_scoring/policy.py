"""The scoring policy (FEAT-05-3).

A `ScoringPolicy` is the immutable, versioned configuration the deterministic
engine evaluates under: per-factor weights, the temporal-decay half-life, the
acceptance threshold, the duplicate-likelihood gate, and the rounding precision
that makes results byte-reproducible. Pinning `policy_version` lets a stored
trust score be interpreted against the exact policy that produced it, and lets a
golden test guard against an unintended change to the scoring behaviour.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .factors import ALL_FACTORS, TrustFactor

# The current policy schema/behaviour version. Bumping it signals that scores are
# not comparable across the boundary; the golden test pins the default output.
TRUST_POLICY_VERSION = 1

# Default per-factor weights (sum == 1.0). Provenance and validation carry the
# most weight (grounded/cited-by-construction, Architecture Baseline); temporal
# and relationship consistency are lighter secondary signals.
_DEFAULT_WEIGHTS: dict[TrustFactor, float] = {
    TrustFactor.SOURCE_CONFIDENCE: 0.15,
    TrustFactor.PROVENANCE_QUALITY: 0.20,
    TrustFactor.EVIDENCE_COMPLETENESS: 0.15,
    TrustFactor.VALIDATION_STATUS: 0.20,
    TrustFactor.OWNERSHIP_CONFIDENCE: 0.10,
    TrustFactor.TEMPORAL_FRESHNESS: 0.05,
    TrustFactor.RELATIONSHIP_CONSISTENCY: 0.05,
    TrustFactor.INGESTION_QUALITY: 0.10,
}

# Deterministic per-source-type base confidence (the real model replacing the
# Sprint 10 interim default). Higher for the most-attested machine sources.
SOURCE_CONFIDENCE: dict[str, float] = {
    "system": 0.90,
    "api": 0.75,
    "document": 0.60,
    "human": 0.60,
    "ai": 0.40,
}


class ScoringPolicy(BaseModel):
    """Immutable trust-scoring policy. Weights are normalized to sum to 1.0 on
    construction, so the composite is always a clean weighted average in
    ``[0, 1]``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: int = TRUST_POLICY_VERSION
    weights: dict[TrustFactor, float] = Field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    # Temporal-freshness decay: score halves every `half_life_days` of age.
    half_life_days: float = Field(default=180.0, gt=0.0)
    # A record scoring at/above this is "accepted" by the trust gate.
    acceptance_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    # A record whose duplicate_likelihood is >= this fails the duplicate gate.
    duplicate_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    # Fixed rounding precision for byte-reproducible scores.
    precision: int = Field(default=6, ge=2, le=12)

    @model_validator(mode="after")
    def _validate_and_normalize(self) -> ScoringPolicy:
        missing = [f.value for f in ALL_FACTORS if f not in self.weights]
        if missing:
            raise ValueError(f"scoring policy is missing weights for: {missing}")
        unknown = [f for f in self.weights if f not in ALL_FACTORS]
        if unknown:
            raise ValueError(f"scoring policy has unknown factor weights: {unknown}")
        # Reject non-finite weights (NaN / +Inf / -Inf) BEFORE the sign/sum checks:
        # NaN silently passes `w < 0` and `total <= 0`, and would otherwise
        # normalize to NaN and produce a NaN composite score. Fail fast instead.
        if not all(math.isfinite(w) for w in self.weights.values()):
            raise ValueError("scoring policy weights must be finite (no NaN or infinity)")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("scoring policy weights must be non-negative")
        # half_life_days already has a field-level ``gt=0`` bound (which rejects
        # NaN); this additionally rejects +Infinity, which would zero out decay.
        if not math.isfinite(self.half_life_days):
            raise ValueError("half_life_days must be finite (no NaN or infinity)")
        # acceptance_threshold and duplicate_threshold are finite by construction:
        # their ``ge``/``le`` [0, 1] field bounds reject NaN and infinity already.
        total = sum(self.weights.values())
        if total <= 0:
            raise ValueError("scoring policy weights must sum to a positive value")
        # Normalize deterministically so the composite is a weighted average.
        object.__setattr__(self, "weights", {f: self.weights[f] / total for f in ALL_FACTORS})
        return self


# The default policy used when a caller does not supply one.
DEFAULT_POLICY = ScoringPolicy()
