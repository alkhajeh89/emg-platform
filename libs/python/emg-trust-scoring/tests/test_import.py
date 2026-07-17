"""Import + public-surface tests (FEAT-05-3)."""

from __future__ import annotations

import emg_trust_scoring as ts


def test_version() -> None:
    assert ts.__version__ == "0.1.0"


def test_public_surface() -> None:
    for name in (
        "TrustFactor",
        "ALL_FACTORS",
        "TrustSignals",
        "ScoringPolicy",
        "DEFAULT_POLICY",
        "evaluate_trust",
        "compute_factor_scores",
        "TrustScoreResult",
        "run_quality_gates",
        "QualityGateReport",
        "evaluate",
        "TrustEvaluation",
        "signals_from_entity",
    ):
        assert hasattr(ts, name), name


def test_counts() -> None:
    assert len(ts.ALL_FACTORS) == 8
    assert len(ts.ALL_CHECKS) == 9
    assert ts.TRUST_POLICY_VERSION == 1
