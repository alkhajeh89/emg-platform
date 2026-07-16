"""The Provenance Record model (Module 6 — Audit, Provenance & Digital
Evidence, FEAT-04-2, Sprint 7).

A `ProvenanceRecord` captures *where a governed action came from* and *how it
reached the audit store* — the origin and lineage of an audit event, beyond
the action itself. It is an **optional, additive** part of an `AuditEvent`:

- Events without provenance are **schema version 1** (every Sprint 6 record),
  and their canonical hash is byte-for-byte unchanged (see
  `emg_audit_pipeline.hashing` — version-aware canonicalization).
- Events *with* provenance are **schema version 2**; the provenance record is
  part of the canonical hash, so tampering with provenance is detected by
  integrity verification exactly like any other immutable field.

Provenance is **producer-supplied** (a service knows its own origin), except
that the audit store still assigns the event's `schema_version`, `sequence_number`,
timing, and hash-chain fields centrally — a producer cannot forge chain state
by supplying provenance. Free-text provenance fields are redacted and bounded
before persistence (`emg_audit_pipeline.validation`), same as `reason`/metadata.

This module defines the *shape* only; hashing, validation, and persistence live
in `emg-audit-pipeline`. See `docs/engineering/sprint-7-design.md`.
"""

from __future__ import annotations

from datetime import datetime

from emg_common_types import Classification, CorrelationId
from pydantic import BaseModel, ConfigDict, Field

# The provenance-model schema version (distinct from the *event* schema_version
# that discriminates v1/v2 events). Bumping this is how the provenance shape
# itself evolves in a later sprint without breaking existing v2 hashes.
PROVENANCE_SCHEMA_VERSION = 1


class TransformationStep(BaseModel):
    """One step in an audit event's transformation history — a record of a
    processing/enrichment stage the underlying action passed through before it
    was captured (e.g. `normalized`, `enriched`, `redacted`). Ordered:
    `ProvenanceRecord.transformation_history` preserves the order steps
    occurred, and that order is part of the canonical hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: str
    timestamp: datetime | None = None
    actor: str | None = None
    detail: str = ""


class EventRef(BaseModel):
    """A reference to a parent/source audit event this event derives from.

    Identified by `(source_principal, event_id)` — the same composite key the
    store uses for idempotency — with an optional `event_hash` so a reference
    can be pinned to a specific immutable record (tamper-evident lineage)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_principal: str
    event_id: str
    event_hash: str | None = None


class ProvenanceRecord(BaseModel):
    """The origin and lineage of an audit event (FEAT-04-2).

    Immutable by construction (`frozen=True`). Every field is hashed for a
    version-2 event, so any later alteration is detectable via integrity
    verification.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Where the action originated.
    source_system: str
    source_component: str | None = None
    originating_actor: str
    originating_principal: str
    correlation_id: CorrelationId | None = None

    # Event time (when the action occurred, per the origin) vs. ingestion time
    # (when the origin handed it off toward the audit store). These are the
    # provenance-side timestamps; the store additionally assigns its own
    # authoritative `AuditEvent.timestamp` / `ingest_time`.
    event_time: datetime
    ingest_time: datetime

    classification: Classification = Classification.INTERNAL

    # Lineage.
    transformation_history: tuple[TransformationStep, ...] = Field(default_factory=tuple)
    parent_event_refs: tuple[EventRef, ...] = Field(default_factory=tuple)

    # Digital-evidence origin (extended and made first-class by the custody
    # ledger in FEAT-04-3).
    evidence_origin: str | None = None
    collection_method: str | None = None

    # Self-describing schema version of the provenance record itself.
    schema_version: int = PROVENANCE_SCHEMA_VERSION
