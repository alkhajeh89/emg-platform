"""HTTP transport DTOs for ADR-027 Stage 4 mutations.

These models describe transport shape only. They do not construct application
commands, perform authorization, negotiate schemas, or access persistence.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ClassificationValue = Literal["UNCLASSIFIED", "INTERNAL", "CONFIDENTIAL", "SECRET"]
EntityLifecycleValue = Literal["proposed", "active", "superseded", "retired"]
VersionStateValue = Literal[
    "proposed",
    "active",
    "deprecated",
    "superseded",
    "archived",
    "retired",
]
EvidenceSourceValue = Literal[
    "email",
    "meeting_minutes",
    "pdf",
    "word_document",
    "sharepoint",
    "teams",
    "jira",
    "manual_entry",
]
EdgeDirectionValue = Literal["directed", "undirected"]
EntityReplacementActionValue = Literal["update", "retire", "restore", "reclassify"]
MAX_TRANSPORT_COLLECTION_ITEMS = 1_000


class MutationTransportModel(BaseModel):
    """Closed, immutable transport-model base."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProvenanceReferenceInput(MutationTransportModel):
    source_principal: str
    event_id: str
    correlation_id: str | None = None
    provenance_record_id: str | None = None
    custody_event_id: str | None = None


class OntologyEntityInput(MutationTransportModel):
    """Caller-visible ontology fields; ownership is assigned by the server."""

    entity_id: str
    entity_type: str
    classification: ClassificationValue
    trust_score: float = Field(ge=0.0, le=1.0)
    provenance_reference: ProvenanceReferenceInput
    lifecycle_status: EntityLifecycleValue = "proposed"
    version: int = Field(default=1, ge=1)
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None
    supersedes: str | None = None
    correlation_id: str | None = None


class EvidenceRefInput(MutationTransportModel):
    evidence_id: str
    source: EvidenceSourceValue
    locator: str
    source_principal: str
    captured_at: AwareDatetime
    description: str | None = None
    event_id: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, str] = Field(
        default_factory=dict, max_length=MAX_TRANSPORT_COLLECTION_ITEMS
    )


class TemporalValidityInput(MutationTransportModel):
    valid_from: AwareDatetime
    valid_until: AwareDatetime | None = None


class TemporalFactInput(MutationTransportModel):
    value: str
    validity: TemporalValidityInput
    evidence: tuple[EvidenceRefInput, ...] = Field(max_length=MAX_TRANSPORT_COLLECTION_ITEMS)
    recorded_at: AwareDatetime
    metadata: dict[str, str] = Field(
        default_factory=dict, max_length=MAX_TRANSPORT_COLLECTION_ITEMS
    )


class TemporalHistoryInput(MutationTransportModel):
    attribute: str
    facts: tuple[TemporalFactInput, ...] = Field(
        default=(), max_length=MAX_TRANSPORT_COLLECTION_ITEMS
    )


class MemoryNodeInput(MutationTransportModel):
    node_id: str
    node_type: str
    label: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    source: str
    confidence: float = Field(ge=0.0, le=1.0)
    classification: ClassificationValue = "INTERNAL"
    owner: str = ""
    lifecycle_status: VersionStateValue = "active"
    supersedes: tuple[str, ...] = Field(default=(), max_length=MAX_TRANSPORT_COLLECTION_ITEMS)
    evidence: tuple[EvidenceRefInput, ...] = Field(max_length=MAX_TRANSPORT_COLLECTION_ITEMS)
    aliases: tuple[str, ...] = Field(default=(), max_length=MAX_TRANSPORT_COLLECTION_ITEMS)
    histories: tuple[TemporalHistoryInput, ...] = Field(
        default=(), max_length=MAX_TRANSPORT_COLLECTION_ITEMS
    )
    ontology_entity_id: str | None = None
    metadata: dict[str, str] = Field(
        default_factory=dict, max_length=MAX_TRANSPORT_COLLECTION_ITEMS
    )


class MemoryEdgeInput(MutationTransportModel):
    edge_id: str
    edge_type: str
    source_id: str
    target_id: str
    direction: EdgeDirectionValue = "directed"
    evidence: tuple[EvidenceRefInput, ...] = Field(max_length=MAX_TRANSPORT_COLLECTION_ITEMS)
    confidence: float = Field(ge=0.0, le=1.0)
    validity: TemporalValidityInput
    created_at: AwareDatetime
    updated_at: AwareDatetime
    classification: ClassificationValue = "INTERNAL"
    metadata: dict[str, str] = Field(
        default_factory=dict, max_length=MAX_TRANSPORT_COLLECTION_ITEMS
    )


class CreateEntityRequest(MutationTransportModel):
    entity: OntologyEntityInput
    as_of: AwareDatetime


class ReplaceEntityRequest(MutationTransportModel):
    replacement: MemoryNodeInput
    action: EntityReplacementActionValue
    as_of: AwareDatetime
    reason: str | None = None


class ReplaceRelationshipRequest(MutationTransportModel):
    replacement: MemoryEdgeInput
    as_of: AwareDatetime


class CloseRelationshipRequest(MutationTransportModel):
    edge_id: str
    as_of: AwareDatetime
    reason: str


class MergeEntitiesRequest(MutationTransportModel):
    survivor_id: str
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_TRANSPORT_COLLECTION_ITEMS)
    as_of: AwareDatetime
    reason: str


class MutationResponse(MutationTransportModel):
    """ADR-030 Revision 4's exact public mutation response projection."""

    tenant_id: str
    revision_number: int
    content_hash: str
    node_count: int
    edge_count: int
    revision_created: bool
    nodes_created: int
    edges_created: int
    node_inputs_merged: int
    edge_inputs_merged: int
    mutation_id: UUID
    audit_reference: str
    replayed: bool
    timestamp: AwareDatetime
