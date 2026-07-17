"""Ingestion request models (FEAT-05-2).

These are the **producer-supplied** portion of an ingestion — everything a
source knows about an entity/relationship *before* the pipeline assigns the
server-controlled fields. Modelled exactly like the Sprint 6 `SubmittedAuditEvent`
security posture:

- **Server-assigned fields are not fields on the request at all** — a producer
  literally cannot supply `entity_id`, `owner`, `provenance_reference`,
  `trust_score`, `version`, or `relationship_id`. The pipeline assigns them from
  the `IngestionContext` (§context.py). This makes owner/provenance/trust
  spoofing structurally impossible, not merely validated away.
- Models are frozen and `extra="forbid"`, so **mass-assignment is rejected**.
- Free-text fields are length-bounded (see `MAX_*`) to prevent oversized-payload
  DoS; the batch itself is size-capped.

`classification`, `effective_from`/`effective_to`, and the domain attributes
remain producer-supplied — the source knows the sensitivity and the real-world
validity window of the fact it is asserting. `natural_key` is the producer's
stable identifier for the thing (used for deterministic idempotency and
duplicate detection); the pipeline never uses it as the canonical id directly.
"""

from __future__ import annotations

from datetime import datetime

from emg_common_types import Classification
from pydantic import BaseModel, ConfigDict, Field

# Bounds — keep ingestion payloads small and prevent oversized-payload DoS.
MAX_NATURAL_KEY_LEN = 512
MAX_ATTRIBUTE_VALUE_LEN = 4096
MAX_ATTRIBUTES = 64
MAX_BATCH_ENTITIES = 1000
MAX_BATCH_RELATIONSHIPS = 2000


class EntityIngestionRequest(BaseModel):
    """A request to ingest one ontology entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # What kind of entity and how to identify it stably (for idempotency).
    entity_type: str
    natural_key: str = Field(min_length=1, max_length=MAX_NATURAL_KEY_LEN)
    # Producer-asserted governance-relevant facts.
    classification: Classification = Classification.INTERNAL
    effective_from: datetime
    effective_to: datetime | None = None
    # Free-form domain attributes (bounded); these become the concrete entity's
    # optional domain fields (validated against the ontology type downstream).
    attributes: dict[str, str] = Field(default_factory=dict)


class RelationshipIngestionRequest(BaseModel):
    """A request to ingest one ontology relationship between two entities,
    identified by their `(entity_type, natural_key)` so the batch can be
    self-referential and endpoint ids are resolved server-side."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_type: str
    from_entity_type: str
    from_natural_key: str = Field(min_length=1, max_length=MAX_NATURAL_KEY_LEN)
    to_entity_type: str
    to_natural_key: str = Field(min_length=1, max_length=MAX_NATURAL_KEY_LEN)
    classification: Classification = Classification.INTERNAL
    effective_from: datetime
    effective_to: datetime | None = None


class IngestionBatch(BaseModel):
    """A batch of entity + relationship requests ingested atomically. Entities
    are persisted before relationships (dependency ordering); the whole batch
    commits or rolls back together."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entities: tuple[EntityIngestionRequest, ...] = ()
    relationships: tuple[RelationshipIngestionRequest, ...] = ()
