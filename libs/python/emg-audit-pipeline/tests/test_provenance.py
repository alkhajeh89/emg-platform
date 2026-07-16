"""Provenance Record Model behavior (FEAT-04-2, Sprint 7): version stamping,
provenance persistence + hashing, tamper detection, and validation/redaction of
oversized or secret-shaped provenance."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_audit_client import (
    EVENT_SCHEMA_VERSION_V1,
    EVENT_SCHEMA_VERSION_V2,
    MAX_PROVENANCE_TRANSFORMATIONS,
    EventRef,
    ProvenanceRecord,
    SubmittedAuditEvent,
    TransformationStep,
)
from emg_audit_pipeline import (
    InMemoryAuditEventStore,
    validate_and_sanitize_provenance,
)
from emg_errors import ValidationError

SP = "emg-svc-identity"


def _provenance(**overrides) -> ProvenanceRecord:
    base = dict(
        source_system="identity",
        source_component="login-handler",
        originating_actor="dev.investigator",
        originating_principal="emg-svc-identity",
        correlation_id="corr-1",
        event_time=datetime(2026, 7, 1, 11, 59, tzinfo=timezone.utc),
        ingest_time=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        transformation_history=(TransformationStep(step="normalized", detail="lowercased"),),
        parent_event_refs=(EventRef(source_principal=SP, event_id="evt-parent"),),
        evidence_origin="sensor-A",
        collection_method="automated",
    )
    base.update(overrides)
    return ProvenanceRecord(**base)


def _event(event_id: str = "evt-1", *, provenance: ProvenanceRecord | None = None):
    return SubmittedAuditEvent(
        event_id=event_id,
        actor="dev.investigator",
        actor_type="human",
        module="identity",
        action="login",
        outcome="success",
        correlation_id="corr-1",
        source_system="identity",
        provenance=provenance,
    )


def test_event_without_provenance_is_version_1() -> None:
    store = InMemoryAuditEventStore()
    e = store.append(_event("evt-1"), source_principal=SP)
    assert e.schema_version == EVENT_SCHEMA_VERSION_V1
    assert e.provenance is None


def test_event_with_provenance_is_version_2_and_persists_provenance() -> None:
    store = InMemoryAuditEventStore()
    e = store.append(_event("evt-2", provenance=_provenance()), source_principal=SP)
    assert e.schema_version == EVENT_SCHEMA_VERSION_V2
    assert e.provenance is not None
    assert e.provenance.source_system == "identity"
    assert e.provenance.transformation_history[0].step == "normalized"
    assert e.provenance.parent_event_refs[0].event_id == "evt-parent"


def test_schema_version_is_server_assigned_from_presence_of_provenance() -> None:
    """A producer cannot force a version; the store derives it from whether
    provenance is present."""
    store = InMemoryAuditEventStore()
    v1 = store.append(_event("v1"), source_principal=SP)
    v2 = store.append(_event("v2", provenance=_provenance()), source_principal=SP)
    assert v1.schema_version == 1 and v2.schema_version == 2


def test_provenance_is_part_of_the_hash_tamper_detected() -> None:
    store = InMemoryAuditEventStore()
    store.append(_event("evt-1"), source_principal=SP)
    e2 = store.append(_event("evt-2", provenance=_provenance()), source_principal=SP)
    assert store.verify_integrity().intact is True

    # Tamper with a provenance field on the stored record: integrity breaks.
    tampered_prov = e2.provenance.model_copy(update={"originating_actor": "attacker"})
    store._unsafe_replace_for_tamper_test(1, e2.model_copy(update={"provenance": tampered_prov}))
    report = store.verify_integrity()
    assert report.intact is False
    assert report.first_broken_sequence == 2


def test_oversized_transformation_history_is_rejected() -> None:
    too_many = tuple(
        TransformationStep(step=f"s{i}") for i in range(MAX_PROVENANCE_TRANSFORMATIONS + 1)
    )
    with pytest.raises(ValidationError) as exc:
        validate_and_sanitize_provenance(_provenance(transformation_history=too_many))
    assert exc.value.error_code == "AUDIT_PROVENANCE_HISTORY_TOO_LARGE"


def test_oversized_provenance_value_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        validate_and_sanitize_provenance(_provenance(evidence_origin="x" * 5000))
    assert exc.value.error_code == "AUDIT_PROVENANCE_VALUE_TOO_LONG"


def test_secret_shaped_provenance_free_text_is_redacted() -> None:
    dirty = _provenance(
        collection_method="fetched with Authorization: Bearer super.secret.jwt",
        transformation_history=(
            TransformationStep(step="enrich", detail="retried with Bearer another.secret.jwt"),
        ),
    )
    clean = validate_and_sanitize_provenance(dirty)
    assert "super.secret.jwt" not in (clean.collection_method or "")
    assert "REDACTED" in (clean.collection_method or "")
    assert "another.secret.jwt" not in clean.transformation_history[0].detail


def test_oversized_provenance_is_rejected_at_ingest_time() -> None:
    """The store's validate_and_sanitize path rejects oversized provenance
    before persistence, so a malformed provenance never reaches the chain."""
    store = InMemoryAuditEventStore()
    with pytest.raises(ValidationError):
        store.append(
            _event("evt-bad", provenance=_provenance(source_system="x" * 5000)),
            source_principal=SP,
        )
