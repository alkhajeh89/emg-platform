"""Combined validation + trust evaluation (FEAT-05-3).

`evaluate` runs the quality gates and computes the trust score from one set of
signals under one policy, returning a single immutable `TrustEvaluation`. This is
"Knowledge Validation & Trust Scoring" as one deterministic operation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .engine import evaluate_trust
from .policy import DEFAULT_POLICY, ScoringPolicy
from .result import TrustScoreResult
from .signals import TrustSignals
from .validation import QualityGateReport, run_quality_gates


class TrustEvaluation(BaseModel):
    """The immutable combined outcome: the quality-gate report and the trust
    score for one record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    quality_gates: QualityGateReport
    trust: TrustScoreResult


def evaluate(signals: TrustSignals, policy: ScoringPolicy = DEFAULT_POLICY) -> TrustEvaluation:
    """Run quality gates and compute the trust score deterministically."""
    return TrustEvaluation(
        quality_gates=run_quality_gates(signals, policy),
        trust=evaluate_trust(signals, policy),
    )
