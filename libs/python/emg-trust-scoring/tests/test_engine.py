"""Trust-scoring engine tests (FEAT-05-3): per-factor calculations, composite,
clamping, determinism, immutability, and the golden reproducibility pin."""

from __future__ import annotations

import emg_trust_scoring as ts
import pytest
from pydantic import ValidationError

F = ts.TrustFactor


def _raw(signals: ts.TrustSignals, factor: ts.TrustFactor) -> float:
    return ts.compute_factor_scores(signals)[factor]


# --- per-factor calculations ------------------------------------------------


def test_source_confidence_by_source_type(now, eff) -> None:
    for source, expected in [
        ("system", 0.9),
        ("api", 0.75),
        ("document", 0.6),
        ("human", 0.6),
        ("ai", 0.4),
    ]:
        s = ts.TrustSignals(as_of=now, source_type=source, effective_from=eff)
        assert _raw(s, F.SOURCE_CONFIDENCE) == expected


def test_provenance_quality_scales_with_links(now, eff) -> None:
    absent = ts.TrustSignals(as_of=now, source_type="system", effective_from=eff)
    assert _raw(absent, F.PROVENANCE_QUALITY) == 0.0
    full = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        provenance_present=True,
        provenance_has_audit_event=True,
        provenance_has_correlation=True,
        provenance_link_count=3,
    )
    assert _raw(full, F.PROVENANCE_QUALITY) == 1.0  # 0.4+0.3+0.1+0.2


def test_evidence_completeness(now, eff) -> None:
    none_required = ts.TrustSignals(as_of=now, source_type="system", effective_from=eff)
    assert _raw(none_required, F.EVIDENCE_COMPLETENESS) == 1.0
    partial = ts.TrustSignals(
        as_of=now, source_type="system", effective_from=eff, evidence_expected=4, evidence_present=1
    )
    assert _raw(partial, F.EVIDENCE_COMPLETENESS) == 0.25
    conflicted = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        evidence_expected=2,
        evidence_present=2,
        evidence_conflicts=1,
    )
    assert _raw(conflicted, F.EVIDENCE_COMPLETENESS) == 0.5  # 1.0 * (1 - 1/2)


def test_validation_status_penalizes_errors(now, eff) -> None:
    nonconformant = ts.TrustSignals(
        as_of=now, source_type="system", effective_from=eff, ontology_conformant=False
    )
    assert _raw(nonconformant, F.VALIDATION_STATUS) == 0.0
    warned = ts.TrustSignals(
        as_of=now, source_type="system", effective_from=eff, validation_warning_count=2
    )
    assert _raw(warned, F.VALIDATION_STATUS) == 0.9  # 1 - 0.05*2


def test_ownership_confidence(now, eff) -> None:
    absent = ts.TrustSignals(as_of=now, source_type="system", effective_from=eff)
    assert _raw(absent, F.OWNERSHIP_CONFIDENCE) == 0.0
    unregistered = ts.TrustSignals(
        as_of=now, source_type="system", effective_from=eff, owner_present=True
    )
    assert _raw(unregistered, F.OWNERSHIP_CONFIDENCE) == 0.6
    registered = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        owner_present=True,
        owner_registered=True,
    )
    assert _raw(registered, F.OWNERSHIP_CONFIDENCE) == 1.0


def test_relationship_consistency(now, eff) -> None:
    none = ts.TrustSignals(as_of=now, source_type="system", effective_from=eff)
    assert _raw(none, F.RELATIONSHIP_CONSISTENCY) == 1.0
    conflicted = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        relationship_total=4,
        relationship_conflicts=1,
    )
    assert _raw(conflicted, F.RELATIONSHIP_CONSISTENCY) == 0.75


def test_ingestion_quality_penalizes_violations(now, eff) -> None:
    clean = ts.TrustSignals(as_of=now, source_type="system", effective_from=eff)
    assert _raw(clean, F.INGESTION_QUALITY) == 1.0
    violated = ts.TrustSignals(
        as_of=now, source_type="system", effective_from=eff, ingestion_bound_violations=1
    )
    assert _raw(violated, F.INGESTION_QUALITY) == 0.5


def test_all_factor_scores_clamped_to_unit_interval(low_trust_signals) -> None:
    for score in ts.compute_factor_scores(low_trust_signals).values():
        assert 0.0 <= score <= 1.0


# --- composite / determinism / immutability --------------------------------


def test_composite_is_weighted_average(high_trust_signals) -> None:
    result = ts.evaluate_trust(high_trust_signals)
    # composite equals the sum of the per-factor contributions
    assert result.score == pytest.approx(sum(c.contribution for c in result.breakdown), abs=1e-6)
    assert result.score == 0.971667  # golden pin (see test_golden_scores)


def test_deterministic_repeated_evaluation(high_trust_signals) -> None:
    a = ts.evaluate_trust(high_trust_signals)
    b = ts.evaluate_trust(high_trust_signals)
    assert a.model_dump() == b.model_dump()


def test_result_is_immutable(high_trust_signals) -> None:
    result = ts.evaluate_trust(high_trust_signals)
    with pytest.raises(ValidationError):
        result.score = 0.1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        result.breakdown[0].raw_score = 0.0  # type: ignore[misc]


def test_breakdown_covers_every_factor(high_trust_signals) -> None:
    result = ts.evaluate_trust(high_trust_signals)
    assert tuple(c.factor for c in result.breakdown) == ts.ALL_FACTORS


# --- golden reproducibility pin --------------------------------------------


def test_golden_scores(high_trust_signals, low_trust_signals) -> None:
    """Pins the composite scores under DEFAULT_POLICY. A change to the factor
    math, weights, or policy version breaks this deterministically (the same
    merge-blocking-gate pattern as the Module 6 golden hash)."""
    assert ts.evaluate_trust(high_trust_signals).score == 0.971667
    assert ts.evaluate_trust(low_trust_signals).score == 0.216667


def test_high_accepted_low_rejected(high_trust_signals, low_trust_signals) -> None:
    assert ts.evaluate_trust(high_trust_signals).accepted is True
    assert ts.evaluate_trust(low_trust_signals).accepted is False


def test_explanation_is_present_and_mentions_every_factor(high_trust_signals) -> None:
    explanation = ts.evaluate_trust(high_trust_signals).explanation
    for factor in ts.ALL_FACTORS:
        assert factor.value in explanation
    assert "trust=" in explanation


def test_score_reproducible_across_signal_field_order(now, eff) -> None:
    # Field order in construction must not change the score (deterministic).
    a = ts.TrustSignals(as_of=now, source_type="system", effective_from=eff, owner_present=True)
    b = ts.TrustSignals(owner_present=True, effective_from=eff, source_type="system", as_of=now)
    assert ts.evaluate_trust(a).score == ts.evaluate_trust(b).score
