"""Minimal Module-6 reference entities (FEAT-05-1).

These exist ONLY so the ontology can *link* to the completed EPIC-04 Audit
Platform records — they are deliberately thin pointer types, not copies. Per the
single-system-of-record principle (Architecture Baseline: Module 6 is the sole
system of record for audit and provenance), the ontology never re-stores audit,
provenance, or custody *content*; it stores the identifiers needed to resolve
the authoritative record in Module 6.

`Decision`, `DecisionOption`, `DecisionRationale`, and `Approval` are
intentionally NOT modeled in Sprint 9: the approved scope excludes Decision
Intelligence ontology semantics (EPIC-08). They are added when that epic lands.
"""

from __future__ import annotations

from typing import Literal

from .core import Artifact


class AuditEventRef(Artifact):
    """A reference to a Module 6 audit event (FEAT-04-1), by its composite key."""

    entity_type: Literal["AuditEventRef"] = "AuditEventRef"
    audit_source_principal: str | None = None
    audit_event_id: str | None = None


class ProvenanceRecordRef(Artifact):
    """A reference to a Module 6 provenance record (FEAT-04-2)."""

    entity_type: Literal["ProvenanceRecordRef"] = "ProvenanceRecordRef"
    provenance_record_id: str | None = None


class CustodyRecordRef(Artifact):
    """A reference to a Module 6 chain-of-custody event (FEAT-04-3)."""

    entity_type: Literal["CustodyRecordRef"] = "CustodyRecordRef"
    custody_event_id: str | None = None
    custody_source_principal: str | None = None


REFERENCE_ENTITY_TYPES: dict[str, type[Artifact]] = {
    "AuditEventRef": AuditEventRef,
    "ProvenanceRecordRef": ProvenanceRecordRef,
    "CustodyRecordRef": CustodyRecordRef,
}
