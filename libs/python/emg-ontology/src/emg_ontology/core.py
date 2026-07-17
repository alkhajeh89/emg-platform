"""Core Ontology archetypes and the shared entity/relationship envelope
(Module 7 — Knowledge Graph, EPIC-05, FEAT-05-1).

The **code models are authoritative** (approved Sprint 9 decision). Every model
is frozen and forbids unknown fields, so an entity or relationship is
conformant-by-construction on the envelope: it cannot be built without a
classification, trust score, and provenance reference, and it cannot smuggle an
extra (mass-assigned) field.

Scope boundaries baked in here:
- `trust_score` is a required *stored value* only; its *calculation* is FEAT-05-3.
- `provenance_reference` is a *reference into Module 6* (audit/provenance/custody),
  never a copy of audit content (single-system-of-record principle).
- No persistence, traversal, or query lives here — that is FEAT-05-2 / FEAT-05-4.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import ClassVar

from emg_common_types import Classification, CorrelationId
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .identifiers import TRUST_SCORE_MAX, TRUST_SCORE_MIN

# --- classification ordering (for the edge-dominance rule) -----------------

# The label vocabulary is owned by emg_common_types (not redefined here). This
# is only an *ordering* over those existing labels, needed for the relationship
# classification-dominance rule (an edge must be at least as classified as
# either endpoint). Enforcement of clearance-based *reads* is out of scope for
# Sprint 9 (no new role, no PEP integration) — this ordering is a modeling
# primitive, not an access-control mechanism.
CLASSIFICATION_RANK: dict[Classification, int] = {
    Classification.UNCLASSIFIED: 0,
    Classification.INTERNAL: 1,
    Classification.CONFIDENTIAL: 2,
    Classification.SECRET: 3,
}


def classification_rank(value: Classification) -> int:
    return CLASSIFICATION_RANK[value]


def dominates(candidate: Classification, floor: Classification) -> bool:
    """True if `candidate` is at least as classified as `floor`."""
    return classification_rank(candidate) >= classification_rank(floor)


# --- lifecycle / mutability / cardinality / direction enums ----------------


class LifecycleStatus(str, Enum):
    """Entity/relationship lifecycle state. Sprint 9 carries the state as a
    field and validates its value; the managed proposed→active→retired state
    machine is FEAT-05-5 (deferred)."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class Mutability(str, Enum):
    """How a relationship may change over time."""

    MUTABLE = "mutable"  # attributes may be updated in place (still versioned)
    APPEND_ONLY = "append_only"  # never updated; corrections are new versions
    SUPERSEDED = "superseded"  # replaced only via an explicit supersession link


class Cardinality(str, Enum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_ONE = "N:1"
    MANY_TO_MANY = "N:M"


class Direction(str, Enum):
    DIRECTED = "directed"  # every ontology relationship is source -> target


# --- provenance reference (into Module 6) ----------------------------------


class ProvenanceReference(BaseModel):
    """A *reference* to the Module 6 audit/provenance/custody record that
    attests where this ontology fact came from. It is deliberately a pointer,
    not a copy: the Knowledge Graph never re-stores audit content (single
    system-of-record). At minimum it carries the Module 6 audit-event composite
    key `(source_principal, event_id)`; provenance-record and custody-event
    identifiers are optional links into FEAT-04-2 / FEAT-04-3 records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_principal: str
    event_id: str
    correlation_id: CorrelationId | None = None
    provenance_record_id: str | None = None
    custody_event_id: str | None = None


# --- the shared entity envelope --------------------------------------------


class Entity(BaseModel):
    """Abstract base for every ontology entity. Concrete domain entities
    subclass an archetype (`Actor`/`Artifact`/`Event`) and pin `entity_type` to
    a `Literal`. Immutable + `extra="forbid"` by construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Archetype is class-level metadata (not a field); used by the descriptor.
    archetype: ClassVar[str] = "Entity"

    # --- canonical identity ---
    entity_id: str
    entity_type: str
    # --- required governance envelope (US-05: "by construction") ---
    classification: Classification
    trust_score: float = Field(ge=TRUST_SCORE_MIN, le=TRUST_SCORE_MAX)
    provenance_reference: ProvenanceReference
    owner: str
    lifecycle_status: LifecycleStatus = LifecycleStatus.PROPOSED
    version: int = Field(default=1, ge=1)
    effective_from: datetime
    effective_to: datetime | None = None
    # --- versioning / supersession (immutable history; no delete) ---
    supersedes: str | None = None
    superseded_by: str | None = None
    # --- audit correlation (propagates onto the future mutation event) ---
    correlation_id: CorrelationId | None = None

    @model_validator(mode="after")
    def _check_effective_dates(self) -> Entity:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be strictly after effective_from")
        if self.supersedes is not None and self.supersedes == self.entity_id:
            raise ValueError("an entity cannot supersede itself")
        return self


class Actor(Entity):
    """Archetype: an entity that can act or be acted upon — organizations,
    people, roles, systems."""

    archetype: ClassVar[str] = "Actor"


class Artifact(Entity):
    """Archetype: a produced or governed thing — documents, policies,
    regulations, controls, evidence, and Module-6 reference records."""

    archetype: ClassVar[str] = "Artifact"


class Event(Entity):
    """Archetype: something that happened at a point/interval in time —
    incidents, generic events, approvals."""

    archetype: ClassVar[str] = "Event"


# --- the governed relationship model ---------------------------------------


class Relationship(BaseModel):
    """A governed, directed edge between two entities. The *catalog*
    (relationships.py) defines which `(relationship_type, source_type,
    target_type)` triples are legal, their cardinality, and their mutability;
    an instance carries the endpoints, its own classification, provenance, and
    versioning. Traversal/query execution is out of scope (FEAT-05-4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_id: str
    relationship_type: str
    from_entity_id: str
    from_entity_type: str
    to_entity_id: str
    to_entity_type: str
    classification: Classification
    provenance_reference: ProvenanceReference
    version: int = Field(default=1, ge=1)
    effective_from: datetime
    effective_to: datetime | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    correlation_id: CorrelationId | None = None

    @model_validator(mode="after")
    def _check_effective_dates(self) -> Relationship:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be strictly after effective_from")
        if self.supersedes is not None and self.supersedes == self.relationship_id:
            raise ValueError("a relationship cannot supersede itself")
        return self
