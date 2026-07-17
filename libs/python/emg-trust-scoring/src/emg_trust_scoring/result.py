"""Trust-score result + explanation models (FEAT-05-3).

The engine's output is **immutable** (frozen) and carries a full per-factor
**breakdown** plus a human-readable explanation, so a trust score is
explainable-by-construction (Architecture Baseline: grounded, cited, explainable;
Module 7 §34) and reproducible.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .factors import TrustFactor


class FactorContribution(BaseModel):
    """One factor's contribution to the composite trust score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    factor: TrustFactor
    raw_score: float  # the factor's normalized sub-score in [0, 1]
    weight: float  # the (normalized) policy weight for this factor
    contribution: float  # weight * raw_score (the composite is the sum of these)


class TrustScoreResult(BaseModel):
    """The immutable result of a trust evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float  # composite confidence in [0, 1]
    accepted: bool  # score >= policy.acceptance_threshold
    policy_version: int
    breakdown: tuple[FactorContribution, ...]
    explanation: str

    def contribution_of(self, factor: TrustFactor) -> FactorContribution:
        for item in self.breakdown:
            if item.factor is factor:
                return item
        raise KeyError(factor)
