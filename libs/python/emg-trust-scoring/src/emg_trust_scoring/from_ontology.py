"""Derive `TrustSignals` from an ontology entity (FEAT-05-3).

A convenience adapter that reads the envelope-derived signals an `emg-ontology`
`Entity` already carries (provenance links, ownership presence, identifier,
effective window, lifecycle) and lets the caller supply the *observations that
live outside the entity* (evidence counts, validation outcomes, relationship
conflicts, ingestion quality, duplicate likelihood). It is the clean integration
point a future live ingestion service would use to compute a real trust score in
place of the FEAT-05-2 interim source-type default — without this library
depending on the ingestion pipeline.
"""

from __future__ import annotations

from datetime import datetime

from emg_ontology import Entity

from .signals import SourceType, TrustSignals


def signals_from_entity(
    entity: Entity,
    *,
    as_of: datetime,
    source_type: SourceType,
    evidence_expected: int = 0,
    evidence_present: int = 0,
    evidence_conflicts: int = 0,
    validation_error_count: int = 0,
    validation_warning_count: int = 0,
    owner_registered: bool = False,
    relationship_total: int = 0,
    relationship_conflicts: int = 0,
    ingestion_redactions: int = 0,
    ingestion_bound_violations: int = 0,
    duplicate_likelihood: float = 0.0,
) -> TrustSignals:
    """Build `TrustSignals` from an entity's envelope plus caller observations.

    Envelope-derived facts (always present by construction on a valid entity):
    provenance is present and references a Module-6 audit event, the identifier
    is present/well-formed, ownership presence, the effective window, and the
    lifecycle state. The entity is treated as ontology-conformant because it is a
    constructed ontology model.
    """
    prov = entity.provenance_reference
    link_count = sum(
        1 for value in (prov.event_id, prov.provenance_record_id, prov.custody_event_id) if value
    )
    return TrustSignals(
        as_of=as_of,
        source_type=source_type,
        provenance_present=True,
        provenance_has_audit_event=bool(prov.event_id),
        provenance_has_correlation=prov.correlation_id is not None,
        provenance_link_count=link_count,
        evidence_expected=evidence_expected,
        evidence_present=evidence_present,
        evidence_conflicts=evidence_conflicts,
        ontology_conformant=True,
        validation_error_count=validation_error_count,
        validation_warning_count=validation_warning_count,
        owner_present=bool(entity.owner),
        owner_registered=owner_registered,
        identifier_present=bool(entity.entity_id),
        identifier_wellformed=entity.entity_id.startswith("ent-"),
        effective_from=entity.effective_from,
        effective_to=entity.effective_to,
        relationship_total=relationship_total,
        relationship_conflicts=relationship_conflicts,
        ingestion_redactions=ingestion_redactions,
        ingestion_bound_violations=ingestion_bound_violations,
        duplicate_likelihood=duplicate_likelihood,
        lifecycle_status=entity.lifecycle_status.value,
    )
