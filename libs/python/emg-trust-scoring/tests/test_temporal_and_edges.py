"""Temporal decay + edge-case tests (FEAT-05-3): freshness decay, expiry,
lifecycle, malformed/conflicting evidence, and duplicate scenarios."""

from __future__ import annotations

from datetime import timedelta

import emg_trust_scoring as ts

F = ts.TrustFactor


def _fresh(signals: ts.TrustSignals) -> float:
    return ts.compute_factor_scores(signals)[F.TEMPORAL_FRESHNESS]


def test_freshness_is_maximal_at_effective_date(eff) -> None:
    s = ts.TrustSignals(as_of=eff, source_type="system", effective_from=eff)
    assert _fresh(s) == 1.0


def test_freshness_halves_after_one_half_life(eff) -> None:
    half_life = ts.DEFAULT_POLICY.half_life_days
    s = ts.TrustSignals(
        as_of=eff + timedelta(days=half_life), source_type="system", effective_from=eff
    )
    assert _fresh(s) == 0.5


def test_freshness_decays_monotonically(eff) -> None:
    ages = [0, 30, 180, 365, 730]
    scores = [
        _fresh(
            ts.TrustSignals(as_of=eff + timedelta(days=a), source_type="system", effective_from=eff)
        )
        for a in ages
    ]
    assert scores == sorted(scores, reverse=True)


def test_future_dated_record_is_fully_fresh(eff) -> None:
    s = ts.TrustSignals(as_of=eff - timedelta(days=10), source_type="system", effective_from=eff)
    assert _fresh(s) == 1.0  # age clamped to >= 0


def test_expired_record_has_zero_freshness(eff) -> None:
    s = ts.TrustSignals(
        as_of=eff + timedelta(days=400),
        source_type="system",
        effective_from=eff,
        effective_to=eff + timedelta(days=365),
    )
    assert _fresh(s) == 0.0


def test_retired_or_superseded_has_zero_freshness(eff) -> None:
    for state in ("retired", "superseded"):
        s = ts.TrustSignals(
            as_of=eff, source_type="system", effective_from=eff, lifecycle_status=state
        )
        assert _fresh(s) == 0.0


# --- edge cases -------------------------------------------------------------


def test_conflicting_evidence_with_no_support_is_zero(now, eff) -> None:
    s = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        evidence_expected=0,
        evidence_present=0,
        evidence_conflicts=3,
    )
    assert ts.compute_factor_scores(s)[F.EVIDENCE_COMPLETENESS] == 0.0


def test_all_default_signals_still_produce_valid_score(now, eff) -> None:
    s = ts.TrustSignals(as_of=now, source_type="human", effective_from=eff)
    result = ts.evaluate_trust(s)
    assert 0.0 <= result.score <= 1.0


def test_malformed_signals_are_rejected_at_construction(now, eff) -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ts.TrustSignals(as_of=now, source_type="system", effective_from=eff, evidence_present=-1)
    with pytest.raises(ValidationError):
        ts.TrustSignals(
            as_of=now, source_type="system", effective_from=eff, duplicate_likelihood=1.5
        )
    with pytest.raises(ValidationError):
        ts.TrustSignals(as_of=now, source_type="martian", effective_from=eff)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ts.TrustSignals(as_of=now, source_type="system", effective_from=eff, injected="x")  # type: ignore[call-arg]


def test_duplicate_likelihood_lowers_confidence_via_gate(now, eff) -> None:
    likely_dupe = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        provenance_present=True,
        provenance_has_audit_event=True,
        owner_present=True,
        owner_registered=True,
        duplicate_likelihood=0.95,
    )
    report = ts.run_quality_gates(likely_dupe)
    dup = report.check("duplicate_confidence")
    assert dup.passed is False and dup.severity == "error"


# --- adversarial: oversized inputs + far-future dates stay finite & stable ---


def test_far_future_effective_from_is_finite_and_deterministic(now) -> None:
    """A record effective ~1000 years out must not overflow or vary between
    runs; age is clamped to >= 0 so freshness stays at its 1.0 cap."""
    far = now.replace(year=now.year + 1000)
    s = ts.TrustSignals(as_of=now, source_type="system", effective_from=far)
    r1 = ts.evaluate_trust(s)
    r2 = ts.evaluate_trust(s)
    assert _fresh(s) == 1.0
    assert 0.0 <= r1.score <= 1.0
    assert r1.model_dump() == r2.model_dump()  # deterministic


def test_extremely_large_evidence_counts_stay_bounded(now, eff) -> None:
    """Enormous evidence counts must keep the factor clamped to [0, 1] with no
    overflow, and remain deterministic."""
    s = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        evidence_expected=10**18,
        evidence_present=10**18,
        evidence_conflicts=10**9,
    )
    score = ts.compute_factor_scores(s)[F.EVIDENCE_COMPLETENESS]
    assert 0.0 <= score <= 1.0
    assert ts.evaluate_trust(s).score == ts.evaluate_trust(s).score  # deterministic


def test_extremely_large_relationship_counts_stay_bounded(now, eff) -> None:
    s = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        relationship_total=10**18,
        relationship_conflicts=10**9,
    )
    score = ts.compute_factor_scores(s)[F.RELATIONSHIP_CONSISTENCY]
    assert 0.0 <= score <= 1.0
    result = ts.evaluate_trust(s)
    assert 0.0 <= result.score <= 1.0
