"""Shared fixtures for the emg-trust-scoring test suite (FEAT-05-3)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_trust_scoring import TrustSignals


@pytest.fixture
def eff() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def now(eff: datetime) -> datetime:
    return eff  # evaluate "as of" the effective date => maximal freshness


@pytest.fixture
def high_trust_signals(now: datetime, eff: datetime) -> TrustSignals:
    """A fully-attested, high-trust record (all factors near maximal)."""
    return TrustSignals(
        as_of=now,
        source_type="system",
        provenance_present=True,
        provenance_has_audit_event=True,
        provenance_has_correlation=True,
        provenance_link_count=2,
        evidence_expected=3,
        evidence_present=3,
        evidence_conflicts=0,
        ontology_conformant=True,
        owner_present=True,
        owner_registered=True,
        identifier_present=True,
        identifier_wellformed=True,
        effective_from=eff,
        relationship_total=4,
        relationship_conflicts=0,
        ingestion_redactions=0,
        ingestion_bound_violations=0,
        duplicate_likelihood=0.0,
        lifecycle_status="active",
    )


@pytest.fixture
def low_trust_signals(now: datetime, eff: datetime) -> TrustSignals:
    """A poorly-attested, low-trust record (many factors near minimal)."""
    return TrustSignals(
        as_of=now,
        source_type="ai",
        provenance_present=False,
        evidence_expected=5,
        evidence_present=1,
        evidence_conflicts=2,
        ontology_conformant=False,
        validation_error_count=2,
        owner_present=False,
        effective_from=eff,
        relationship_total=3,
        relationship_conflicts=2,
        ingestion_redactions=1,
        duplicate_likelihood=0.9,
        lifecycle_status="active",
    )
