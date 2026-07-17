"""Quality-gate validation tests (FEAT-05-3): each typed check and the report
aggregation."""

from __future__ import annotations

import emg_trust_scoring as ts


def test_all_gates_pass_for_high_trust(high_trust_signals) -> None:
    report = ts.run_quality_gates(high_trust_signals)
    assert report.passed is True
    assert report.error_count == 0
    assert {c.name for c in report.checks} == set(ts.ALL_CHECKS)
    assert all(c.passed for c in report.checks)


def test_low_trust_fails_with_multiple_errors(low_trust_signals) -> None:
    report = ts.run_quality_gates(low_trust_signals)
    assert report.passed is False
    assert report.error_count >= 1
    # provenance absent, ownership absent, ontology non-conformant, duplicate high
    failed = {c.name for c in report.checks if not c.passed}
    assert "provenance_integrity" in failed
    assert "ownership_consistency" in failed
    assert "ontology_consistency" in failed
    assert "duplicate_confidence" in failed


def test_missing_provenance_is_an_error(now, eff) -> None:
    s = ts.TrustSignals(
        as_of=now, source_type="system", effective_from=eff, provenance_present=False
    )
    check = ts.run_quality_gates(s).check("provenance_integrity")
    assert check.passed is False and check.severity == "error"


def test_provenance_without_audit_event_is_a_warning(now, eff) -> None:
    s = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        provenance_present=True,
        provenance_has_audit_event=False,
    )
    check = ts.run_quality_gates(s).check("provenance_integrity")
    assert check.passed is False and check.severity == "warning"


def test_warnings_do_not_fail_the_report(now, eff) -> None:
    # A single warning-severity failure (unregistered owner) leaves passed=True.
    s = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        provenance_present=True,
        provenance_has_audit_event=True,
        owner_present=True,
        owner_registered=False,
    )
    report = ts.run_quality_gates(s)
    assert report.passed is True
    assert report.warning_count >= 1
    assert report.check("ownership_consistency").severity == "warning"


def test_malformed_identifier_is_an_error(now, eff) -> None:
    s = ts.TrustSignals(
        as_of=now, source_type="system", effective_from=eff, identifier_wellformed=False
    )
    check = ts.run_quality_gates(s).check("identifier_consistency")
    assert check.passed is False and check.severity == "error"


def test_invalid_effective_dates_is_an_error(now, eff) -> None:
    s = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        effective_to=eff,
    )  # effective_to not after effective_from
    check = ts.run_quality_gates(s).check("temporal_validation")
    assert check.passed is False and check.severity == "error"


def test_relationship_conflict_is_an_error(now, eff) -> None:
    s = ts.TrustSignals(
        as_of=now,
        source_type="system",
        effective_from=eff,
        relationship_total=3,
        relationship_conflicts=1,
    )
    check = ts.run_quality_gates(s).check("relationship_consistency")
    assert check.passed is False and check.severity == "error"


def test_report_is_immutable(high_trust_signals) -> None:
    import pytest
    from pydantic import ValidationError

    report = ts.run_quality_gates(high_trust_signals)
    with pytest.raises(ValidationError):
        report.passed = False  # type: ignore[misc]


def test_combined_evaluation_bundles_gates_and_trust(high_trust_signals) -> None:
    ev = ts.evaluate(high_trust_signals)
    assert ev.quality_gates.passed is True
    assert ev.trust.score == 0.971667
