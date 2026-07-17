"""Module-6 audit-contract emission for graph mutations (FEAT-05-2).

Every graph mutation produces a `SubmittedAuditEvent` (the `emg-audit-client`
producer contract) that a caller hands to an `AuditSink` — reusing the completed
EPIC-04 Audit Platform rather than building a parallel record (single system of
record). The four actions come from the ontology's own audit contract
(`emg_ontology.audit`): `entity.created`, `relationship.created`,
`entity.superseded`, `relationship.superseded`.

Two integrity properties:
- **Provenance is a reference, not a copy.** The entity/relationship that the
  pipeline persists carries a `ProvenanceReference` pointing at the audit event
  emitted for its creation (`source_principal` + the deterministic mutation
  `event_id`). No audit content is duplicated into the graph.
- **Correlation is preserved.** The context's correlation id rides on every
  emitted audit event (ADR-015), while the entity/provenance stay
  correlation-agnostic so re-ingestion remains byte-identical (idempotent).
"""

from __future__ import annotations

from emg_audit_client import SubmittedAuditEvent
from emg_common_types import Classification
from emg_ontology import ProvenanceReference
from emg_ontology.audit import AUDIT_MODULE, GraphMutationAction, mutation_audit_metadata

from .context import IngestionContext
from .idempotency import mutation_event_id_for


def mutation_event_id(
    context: IngestionContext, action: GraphMutationAction, subject_id: str
) -> str:
    """The deterministic Module-6 audit event id for a mutation (idempotent: a
    replayed ingestion maps to the same event id)."""
    return mutation_event_id_for(context.source_principal, action, subject_id)


def provenance_reference_for(
    context: IngestionContext, action: GraphMutationAction, subject_id: str
) -> ProvenanceReference:
    """A provenance reference into Module 6 pointing at the audit event that
    records this mutation. Correlation is intentionally omitted here (it lives on
    the audit event) so a persisted record stays byte-identical across replays."""
    return ProvenanceReference(
        source_principal=context.source_principal,
        event_id=mutation_event_id(context, action, subject_id),
    )


def build_mutation_event(
    *,
    context: IngestionContext,
    action: GraphMutationAction,
    subject_id: str,
    subject_type: str,
    classification: Classification,
) -> SubmittedAuditEvent:
    """Build the `SubmittedAuditEvent` for one graph mutation. `event_id` is
    deterministic so Module 6 treats a replayed mutation idempotently. Metadata
    carries identifiers/types only — never entity attribute content."""
    return SubmittedAuditEvent(
        event_id=mutation_event_id(context, action, subject_id),
        actor=context.source_principal,
        actor_type="service",
        module=AUDIT_MODULE,
        action=action,
        outcome="success",
        correlation_id=context.correlation_id,
        resource_type=subject_type,
        resource_id=subject_id,
        classification=classification,
        source_system=context.source_type,
        metadata=mutation_audit_metadata(
            action=action,
            subject_id=subject_id,
            subject_type=subject_type,
            schema_version=_ontology_schema_version(),
        ),
    )


def _ontology_schema_version() -> int:
    from emg_ontology import ONTOLOGY_SCHEMA_VERSION

    return ONTOLOGY_SCHEMA_VERSION
