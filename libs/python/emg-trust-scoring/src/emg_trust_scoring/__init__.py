"""emg_trust_scoring — deterministic Knowledge Validation & Trust Scoring
(Module 7 — Knowledge Graph Platform, EPIC-05, FEAT-05-3). Added Sprint 11.

Library-first, the same contract-first pattern as the other Module 7 libraries:
this package computes an **immutable, explainable composite trust (confidence)
score from observable signals** — never a caller-supplied value — under a
versioned weighting policy, and runs a suite of typed **quality-gate**
validation checks. It is pure and deterministic (identical signals + policy ⇒
identical output), so trust cannot be spoofed and evaluations are reproducible.

Out of scope for Sprint 11 (deliberately): persistence, any service, Neo4j, the
Semantic Layer (FEAT-05-4), lifecycle management (FEAT-05-5), retrieval, search,
embeddings, AI, and UI. Wiring the engine into the ingestion pipeline (replacing
the FEAT-05-2 interim default) is a follow-up for the future live service.
"""

from .engine import compute_factor_scores, evaluate_trust
from .evaluate import TrustEvaluation, evaluate
from .factors import ALL_FACTORS, TrustFactor
from .from_ontology import signals_from_entity
from .policy import (
    DEFAULT_POLICY,
    SOURCE_CONFIDENCE,
    TRUST_POLICY_VERSION,
    ScoringPolicy,
)
from .result import FactorContribution, TrustScoreResult
from .signals import LifecycleValue, SourceType, TrustSignals
from .validation import (
    ALL_CHECKS,
    QualityCheck,
    QualityGateReport,
    QualitySeverity,
    run_quality_gates,
)

__version__ = "0.1.0"

__all__ = [
    # factors
    "TrustFactor",
    "ALL_FACTORS",
    # signals
    "TrustSignals",
    "SourceType",
    "LifecycleValue",
    # policy
    "ScoringPolicy",
    "DEFAULT_POLICY",
    "TRUST_POLICY_VERSION",
    "SOURCE_CONFIDENCE",
    # engine + result
    "evaluate_trust",
    "compute_factor_scores",
    "TrustScoreResult",
    "FactorContribution",
    # quality gates
    "run_quality_gates",
    "QualityCheck",
    "QualityGateReport",
    "QualitySeverity",
    "ALL_CHECKS",
    # combined evaluation
    "evaluate",
    "TrustEvaluation",
    # ontology integration
    "signals_from_entity",
    "__version__",
]
