"""Memory graph edges (FEAT-05-6, Deliverable 1).

A `MemoryEdge` connects two nodes and carries every field the sprint requires: a
relationship type, a direction, evidence references, a confidence score, a valid
interval (`valid_from`/`valid_until` via `TemporalValidity`), and metadata. Edges
are immutable and evidence-backed; "changing" a relationship means adding a new
edge and closing the old one's validity (temporal memory), never mutating in place.

`from_relationship` adapts an ontology `Relationship` into an edge without
duplicating the ontology model.
"""

from __future__ import annotations

from datetime import datetime

from emg_common_types import Classification
from emg_ontology import Relationship
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import EdgeDirection
from .evidence import EvidenceRef
from .labels import SafeLabel
from .limits import MAX_EVIDENCE_REFS
from .metadata import Metadata
from .temporal import TemporalValidity


class MemoryEdge(BaseModel):
    """An immutable, evidence-backed, time-bounded relationship between nodes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge_id: SafeLabel
    edge_type: SafeLabel
    source_id: SafeLabel
    target_id: SafeLabel
    direction: EdgeDirection = EdgeDirection.DIRECTED
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    validity: TemporalValidity
    created_at: datetime
    updated_at: datetime
    classification: Classification = Classification.INTERNAL
    metadata: Metadata = Metadata()

    @field_validator("evidence")
    @classmethod
    def _bounded_unique_evidence(cls, value: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
        if len(value) > MAX_EVIDENCE_REFS:
            raise ValueError(f"too many evidence refs (max {MAX_EVIDENCE_REFS})")
        by_id = {e.evidence_id: e for e in value}
        return tuple(sorted(by_id.values(), key=lambda e: e.evidence_id))

    @model_validator(mode="after")
    def _validate(self) -> MemoryEdge:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be >= created_at")
        if self.source_id == self.target_id:
            raise ValueError("self-loops are not permitted (source_id == target_id)")
        return self

    def is_active_at(self, moment: datetime) -> bool:
        """True iff this edge's valid interval contains `moment`."""
        return self.validity.contains(moment)

    def endpoints(self) -> tuple[str, str]:
        """(source_id, target_id) — for undirected edges the pair is orientation
        as stored; callers treat both directions as equivalent."""
        return (self.source_id, self.target_id)

    @classmethod
    def from_relationship(
        cls,
        relationship: Relationship,
        *,
        evidence: tuple[EvidenceRef, ...],
        confidence: float,
        direction: EdgeDirection = EdgeDirection.DIRECTED,
        updated_at: datetime | None = None,
        metadata: Metadata | None = None,
    ) -> MemoryEdge:
        """Adapt an ontology `Relationship` into a `MemoryEdge`, reusing its id,
        type, endpoints, classification and effective interval."""
        return cls(
            edge_id=relationship.relationship_id,
            edge_type=relationship.relationship_type,
            source_id=relationship.from_entity_id,
            target_id=relationship.to_entity_id,
            direction=direction,
            evidence=evidence,
            confidence=confidence,
            validity=TemporalValidity(
                valid_from=relationship.effective_from,
                valid_until=relationship.effective_to,
            ),
            created_at=relationship.effective_from,
            updated_at=updated_at or relationship.effective_from,
            classification=relationship.classification,
            metadata=metadata or Metadata(),
        )
