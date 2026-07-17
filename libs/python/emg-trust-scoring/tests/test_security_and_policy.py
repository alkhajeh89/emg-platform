"""Security + policy tests (FEAT-05-3): trust cannot be spoofed, calculations
are deterministic/reproducible, output is immutable, a single manipulated signal
cannot dominate, and the policy is validated/normalized. Plus the ontology
integration helper."""

from __future__ import annotations

import math

import emg_trust_scoring as ts
import pytest
from pydantic import ValidationError

# --- trust cannot be spoofed -----------------------------------------------


def test_signals_have_no_trust_field() -> None:
    fields = set(ts.TrustSignals.model_fields)
    for forbidden in ("trust", "trust_score", "score", "confidence"):
        assert forbidden not in fields


def test_signals_reject_extra_fields(now, eff) -> None:
    with pytest.raises(ValidationError):
        ts.TrustSignals(as_of=now, source_type="system", effective_from=eff, trust_score=1.0)  # type: ignore[call-arg]


def test_signals_are_immutable(high_trust_signals) -> None:
    with pytest.raises(ValidationError):
        high_trust_signals.source_type = "ai"  # type: ignore[misc]


def test_manipulated_single_signal_cannot_dominate(now, eff) -> None:
    """Inflating one signal past its natural bound cannot push the composite up:
    evidence_present far above evidence_expected still caps that factor at 1.0,
    so the manipulated factor contributes at most its weight."""
    honest = ts.TrustSignals(
        as_of=now, source_type="ai", effective_from=eff, evidence_expected=2, evidence_present=2
    )
    inflated = ts.TrustSignals(
        as_of=now,
        source_type="ai",
        effective_from=eff,
        evidence_expected=2,
        evidence_present=100000,
    )
    fs_h = ts.compute_factor_scores(honest)[ts.TrustFactor.EVIDENCE_COMPLETENESS]
    fs_i = ts.compute_factor_scores(inflated)[ts.TrustFactor.EVIDENCE_COMPLETENESS]
    assert fs_h == fs_i == 1.0  # capped; no extra credit for inflation
    # and the overall score is identical (no domination)
    assert ts.evaluate_trust(honest).score == ts.evaluate_trust(inflated).score


def test_reproducible_from_serialized_signals(high_trust_signals) -> None:
    dumped = high_trust_signals.model_dump()
    rebuilt = ts.TrustSignals(**dumped)
    assert (
        ts.evaluate_trust(rebuilt).model_dump()
        == ts.evaluate_trust(high_trust_signals).model_dump()
    )


# --- policy -----------------------------------------------------------------


def test_default_policy_weights_sum_to_one() -> None:
    assert sum(ts.DEFAULT_POLICY.weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(ts.DEFAULT_POLICY.weights) == set(ts.ALL_FACTORS)


def test_policy_normalizes_arbitrary_weights() -> None:
    doubled = {f: ts.DEFAULT_POLICY.weights[f] * 2 for f in ts.ALL_FACTORS}
    policy = ts.ScoringPolicy(weights=doubled)
    assert sum(policy.weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_policy_rejects_missing_or_unknown_factor_weights() -> None:
    partial = {ts.TrustFactor.SOURCE_CONFIDENCE: 1.0}
    with pytest.raises(ValidationError):
        ts.ScoringPolicy(weights=partial)


def test_policy_is_immutable() -> None:
    with pytest.raises(ValidationError):
        ts.DEFAULT_POLICY.half_life_days = 10.0  # type: ignore[misc]


def test_policy_changes_score_deterministically(high_trust_signals) -> None:
    # A policy weighting everything on source confidence yields exactly the
    # source-confidence sub-score.
    only_source = {
        f: (1.0 if f is ts.TrustFactor.SOURCE_CONFIDENCE else 0.0) for f in ts.ALL_FACTORS
    }
    policy = ts.ScoringPolicy(weights=only_source)
    result = ts.evaluate_trust(high_trust_signals, policy)
    assert result.score == 0.9  # system source confidence


# --- adversarial: non-finite policy inputs must be rejected (fail fast) ------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_policy_rejects_non_finite_weight(bad: float) -> None:
    """A NaN/+Inf/-Inf weight must raise, never normalize into a NaN score."""
    weights = {f: (bad if f is ts.TrustFactor.SOURCE_CONFIDENCE else 0.1) for f in ts.ALL_FACTORS}
    with pytest.raises(ValidationError):
        ts.ScoringPolicy(weights=weights)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_policy_rejects_non_finite_half_life(bad: float) -> None:
    with pytest.raises(ValidationError):
        ts.ScoringPolicy(half_life_days=bad)


def test_no_policy_can_produce_a_nan_score(high_trust_signals, low_trust_signals) -> None:
    """Belt-and-suspenders: because non-finite policy inputs are rejected at
    construction, every constructible policy yields a finite score in [0, 1]."""
    for signals in (high_trust_signals, low_trust_signals):
        score = ts.evaluate_trust(signals).score
        assert math.isfinite(score)
        assert 0.0 <= score <= 1.0


# --- ontology integration helper -------------------------------------------


def test_signals_from_entity_derives_envelope_signals(now, eff) -> None:
    from emg_ontology import Person, ProvenanceReference

    entity = Person(
        entity_id="ent-abc",
        classification="INTERNAL",
        trust_score=0.5,  # ignored by the trust engine — recomputed from signals
        provenance_reference=ProvenanceReference(
            source_principal="svc", event_id="kg-1", correlation_id="corr-1"
        ),
        owner="bu-1",
        effective_from=eff,
    )
    signals = ts.signals_from_entity(entity, as_of=now, source_type="system", owner_registered=True)
    assert signals.provenance_present is True
    assert signals.provenance_has_audit_event is True
    assert signals.provenance_has_correlation is True
    assert signals.owner_present is True and signals.owner_registered is True
    assert signals.identifier_wellformed is True
    assert signals.lifecycle_status == "proposed"  # Person default lifecycle
    # the entity's own trust_score field is NOT used as an input
    assert "trust" not in signals.model_dump()
