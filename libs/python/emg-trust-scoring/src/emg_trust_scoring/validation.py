"""Advanced validation — quality gates (FEAT-05-3).

Beyond the pipeline's structural ontology conformance (FEAT-05-1/05-2), these are
the **quality gates**: semantic/quality checks over the observable signals, each
returning a typed `QualityCheck`. They are pure and deterministic. A gate that
fails at `error` severity fails the overall `QualityGateReport`; a `warning` is
advisory and does not fail the report. The report also feeds trust scoring (the
validation-status factor) via the same signals.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .policy import DEFAULT_POLICY, ScoringPolicy
from .signals import TrustSignals

QualitySeverity = Literal["info", "warning", "error"]

# Stable check names (used in reports and pinned by the golden test).
CHECK_EVIDENCE_COMPLETENESS = "evidence_completeness"
CHECK_PROVENANCE_INTEGRITY = "provenance_integrity"
CHECK_OWNERSHIP_CONSISTENCY = "ownership_consistency"
CHECK_IDENTIFIER_CONSISTENCY = "identifier_consistency"
CHECK_ONTOLOGY_CONSISTENCY = "ontology_consistency"
CHECK_RELATIONSHIP_CONSISTENCY = "relationship_consistency"
CHECK_DUPLICATE_CONFIDENCE = "duplicate_confidence"
CHECK_TEMPORAL_VALIDATION = "temporal_validation"
CHECK_LIFECYCLE_VALIDATION = "lifecycle_validation"

ALL_CHECKS: tuple[str, ...] = (
    CHECK_EVIDENCE_COMPLETENESS,
    CHECK_PROVENANCE_INTEGRITY,
    CHECK_OWNERSHIP_CONSISTENCY,
    CHECK_IDENTIFIER_CONSISTENCY,
    CHECK_ONTOLOGY_CONSISTENCY,
    CHECK_RELATIONSHIP_CONSISTENCY,
    CHECK_DUPLICATE_CONFIDENCE,
    CHECK_TEMPORAL_VALIDATION,
    CHECK_LIFECYCLE_VALIDATION,
)


class QualityCheck(BaseModel):
    """One typed quality-gate outcome. `severity` is `info` when the check
    passes; when it fails it is `warning` (advisory) or `error` (blocking)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    passed: bool
    severity: QualitySeverity
    detail: str


class QualityGateReport(BaseModel):
    """The immutable result of running all quality gates over one set of
    signals. `passed` is True iff no check failed at `error` severity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    checks: tuple[QualityCheck, ...]
    error_count: int
    warning_count: int

    def check(self, name: str) -> QualityCheck:
        for c in self.checks:
            if c.name == name:
                return c
        raise KeyError(name)


def _ok(name: str, detail: str) -> QualityCheck:
    return QualityCheck(name=name, passed=True, severity="info", detail=detail)


def _fail(name: str, severity: QualitySeverity, detail: str) -> QualityCheck:
    return QualityCheck(name=name, passed=False, severity=severity, detail=detail)


def _evidence_completeness(s: TrustSignals) -> QualityCheck:
    if s.evidence_expected == 0:
        return _ok(CHECK_EVIDENCE_COMPLETENESS, "no evidence required")
    if s.evidence_present >= s.evidence_expected and s.evidence_conflicts == 0:
        return _ok(
            CHECK_EVIDENCE_COMPLETENESS, f"{s.evidence_present}/{s.evidence_expected} present"
        )
    if s.evidence_conflicts > 0:
        return _fail(
            CHECK_EVIDENCE_COMPLETENESS,
            "error",
            f"{s.evidence_conflicts} conflicting evidence item(s)",
        )
    return _fail(
        CHECK_EVIDENCE_COMPLETENESS,
        "error",
        f"incomplete evidence {s.evidence_present}/{s.evidence_expected}",
    )


def _provenance_integrity(s: TrustSignals) -> QualityCheck:
    if not s.provenance_present:
        return _fail(CHECK_PROVENANCE_INTEGRITY, "error", "no provenance reference")
    if not s.provenance_has_audit_event:
        return _fail(
            CHECK_PROVENANCE_INTEGRITY, "warning", "provenance present but no audit-event link"
        )
    return _ok(CHECK_PROVENANCE_INTEGRITY, f"{s.provenance_link_count} Module-6 link(s)")


def _ownership_consistency(s: TrustSignals) -> QualityCheck:
    if not s.owner_present:
        return _fail(CHECK_OWNERSHIP_CONSISTENCY, "error", "no owner assigned")
    if not s.owner_registered:
        return _fail(CHECK_OWNERSHIP_CONSISTENCY, "warning", "owner not in the ownership registry")
    return _ok(CHECK_OWNERSHIP_CONSISTENCY, "owner present and registered")


def _identifier_consistency(s: TrustSignals) -> QualityCheck:
    if not s.identifier_present:
        return _fail(CHECK_IDENTIFIER_CONSISTENCY, "error", "no canonical identifier")
    if not s.identifier_wellformed:
        return _fail(CHECK_IDENTIFIER_CONSISTENCY, "error", "malformed canonical identifier")
    return _ok(CHECK_IDENTIFIER_CONSISTENCY, "identifier present and well-formed")


def _ontology_consistency(s: TrustSignals) -> QualityCheck:
    if not s.ontology_conformant:
        return _fail(CHECK_ONTOLOGY_CONSISTENCY, "error", "not ontology-conformant")
    if s.validation_error_count > 0:
        return _fail(
            CHECK_ONTOLOGY_CONSISTENCY, "error", f"{s.validation_error_count} validation error(s)"
        )
    if s.validation_warning_count > 0:
        return _fail(
            CHECK_ONTOLOGY_CONSISTENCY,
            "warning",
            f"{s.validation_warning_count} validation warning(s)",
        )
    return _ok(CHECK_ONTOLOGY_CONSISTENCY, "ontology-conformant, no validation issues")


def _relationship_consistency(s: TrustSignals) -> QualityCheck:
    if s.relationship_conflicts > 0:
        return _fail(
            CHECK_RELATIONSHIP_CONSISTENCY,
            "error",
            f"{s.relationship_conflicts}/{s.relationship_total} relationship conflict(s)",
        )
    return _ok(CHECK_RELATIONSHIP_CONSISTENCY, "no relationship conflicts")


def _duplicate_confidence(s: TrustSignals, policy: ScoringPolicy) -> QualityCheck:
    if s.duplicate_likelihood >= policy.duplicate_threshold:
        return _fail(
            CHECK_DUPLICATE_CONFIDENCE,
            "error",
            f"duplicate likelihood {s.duplicate_likelihood:g} >= {policy.duplicate_threshold:g}",
        )
    return _ok(CHECK_DUPLICATE_CONFIDENCE, f"duplicate likelihood {s.duplicate_likelihood:g}")


def _temporal_validation(s: TrustSignals) -> QualityCheck:
    if s.effective_to is not None and s.effective_to <= s.effective_from:
        return _fail(CHECK_TEMPORAL_VALIDATION, "error", "effective_to is not after effective_from")
    if s.effective_to is not None and s.as_of >= s.effective_to:
        return _fail(CHECK_TEMPORAL_VALIDATION, "warning", "record is past its effective window")
    return _ok(CHECK_TEMPORAL_VALIDATION, "effective window is valid and current")


def _lifecycle_validation(s: TrustSignals) -> QualityCheck:
    if s.lifecycle_status in ("superseded", "retired"):
        return _fail(
            CHECK_LIFECYCLE_VALIDATION,
            "warning",
            f"record lifecycle is {s.lifecycle_status} (not current)",
        )
    return _ok(CHECK_LIFECYCLE_VALIDATION, f"lifecycle is {s.lifecycle_status}")


def run_quality_gates(
    signals: TrustSignals, policy: ScoringPolicy = DEFAULT_POLICY
) -> QualityGateReport:
    """Run every quality gate deterministically and aggregate a typed report."""
    checks = (
        _evidence_completeness(signals),
        _provenance_integrity(signals),
        _ownership_consistency(signals),
        _identifier_consistency(signals),
        _ontology_consistency(signals),
        _relationship_consistency(signals),
        _duplicate_confidence(signals, policy),
        _temporal_validation(signals),
        _lifecycle_validation(signals),
    )
    error_count = sum(1 for c in checks if not c.passed and c.severity == "error")
    warning_count = sum(1 for c in checks if not c.passed and c.severity == "warning")
    return QualityGateReport(
        passed=error_count == 0,
        checks=checks,
        error_count=error_count,
        warning_count=warning_count,
    )
