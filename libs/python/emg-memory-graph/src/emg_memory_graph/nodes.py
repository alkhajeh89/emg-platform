"""Memory graph nodes (FEAT-05-6, Deliverable 1).

A `MemoryNode` is the immutable unit of enterprise memory. It carries every field
the sprint requires — a UUID (`node_id`), entity type, created/updated timestamps,
source, confidence score, and metadata — plus the concerns that make it *memory*
rather than a row: mandatory evidence (no assertion without provenance), resolution
aliases, and per-attribute temporal histories. `from_entity` adapts an ontology
`Entity` (as produced by the ingestion pipeline) into a node without duplicating
the ontology's model.

Extensibility: `node_type` is a free-form `SafeLabel` (the `MemoryNodeType` enum is
the canonical vocabulary but not a closed set), so new domain concepts can be added
without a breaking change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from emg_common_types import Classification
from emg_knowledge_lifecycle import VersionState
from emg_ontology import Entity
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .evidence import EvidenceRef
from .labels import SafeLabel, SafeText
from .limits import MAX_ALIASES, MAX_EVIDENCE_REFS, MAX_SUPERSEDES
from .metadata import Metadata
from .temporal import TemporalHistory


class MemoryNode(BaseModel):
    """An immutable, evidence-backed node in the Enterprise Memory Graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: SafeLabel
    node_type: SafeLabel
    label: SafeText
    created_at: datetime
    updated_at: datetime
    source: SafeLabel
    confidence: float = Field(ge=0.0, le=1.0)
    classification: Classification = Classification.INTERNAL
    owner: SafeLabel | Literal[""] = ""
    lifecycle_status: VersionState = VersionState.ACTIVE
    supersedes: tuple[SafeLabel, ...] = ()
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    aliases: tuple[SafeText, ...] = ()
    histories: tuple[TemporalHistory, ...] = ()
    ontology_entity_id: SafeLabel | None = None
    metadata: Metadata = Metadata()

    @field_validator("evidence")
    @classmethod
    def _bounded_unique_evidence(cls, value: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
        if len(value) > MAX_EVIDENCE_REFS:
            raise ValueError(f"too many evidence refs (max {MAX_EVIDENCE_REFS})")
        by_id = {e.evidence_id: e for e in value}
        return tuple(sorted(by_id.values(), key=lambda e: e.evidence_id))

    @field_validator("aliases")
    @classmethod
    def _sorted_unique_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > MAX_ALIASES:
            raise ValueError(f"too many aliases (max {MAX_ALIASES})")
        return tuple(sorted(set(value)))

    @field_validator("supersedes")
    @classmethod
    def _bounded_unique_supersedes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > MAX_SUPERSEDES:
            raise ValueError(f"too many supersedes references (max {MAX_SUPERSEDES})")
        if len(value) != len(set(value)):
            raise ValueError("duplicate node_id in supersedes")
        return tuple(sorted(value))

    @field_validator("histories")
    @classmethod
    def _unique_history_attributes(
        cls, value: tuple[TemporalHistory, ...]
    ) -> tuple[TemporalHistory, ...]:
        attrs = [h.attribute for h in value]
        if len(attrs) != len(set(attrs)):
            raise ValueError("duplicate temporal-history attribute on one node")
        return tuple(sorted(value, key=lambda h: h.attribute))

    @model_validator(mode="after")
    def _timestamps_ordered(self) -> MemoryNode:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be >= created_at")
        return self

    def history_for(self, attribute: str) -> TemporalHistory | None:
        """The temporal history for one attribute (e.g. ``"owner"``), or None."""
        for history in self.histories:
            if history.attribute == attribute:
                return history
        return None

    @classmethod
    def from_entity(
        cls,
        entity: Entity,
        *,
        label: str,
        evidence: tuple[EvidenceRef, ...],
        updated_at: datetime | None = None,
        aliases: tuple[str, ...] = (),
        histories: tuple[TemporalHistory, ...] = (),
        metadata: Metadata | None = None,
    ) -> MemoryNode:
        """Adapt an ontology `Entity` into a `MemoryNode`, reusing its id, type,
        classification, trust score (as confidence), provenance principal (as
        source) and effective_from (as created_at)."""
        return cls(
            node_id=entity.entity_id,
            node_type=entity.entity_type,
            label=label,
            created_at=entity.effective_from,
            updated_at=updated_at or entity.effective_from,
            source=entity.provenance_reference.source_principal,
            confidence=entity.trust_score,
            classification=entity.classification,
            owner=entity.owner,
            evidence=evidence,
            aliases=aliases,
            histories=histories,
            ontology_entity_id=entity.entity_id,
            metadata=metadata or Metadata(),
        )
