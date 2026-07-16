"""The AuditEvent model (Module 6 — Audit, Provenance & Digital Evidence,
FEAT-04-1).

An `AuditEvent` is the immutable, non-repudiable record of one governed
action (ADR-015 §Decision: audit is "the immutable, non-repudiable record of
governed actions", distinct from the higher-volume observability logs
`emg_telemetry` emits). This module defines the *shape* only; the append-only
store, hashing, sequencing, and integrity verification live in
`emg-audit-pipeline`.

Field ownership (see `docs/engineering/sprint-6-design.md`):

- **Producer-supplied** fields describe the governed action a service
  observed (`actor`, `action`, `outcome`, `correlation_id`, ...). A producer
  builds a `SubmittedAuditEvent` and hands it to the audit store.
- **Server-assigned** fields are set centrally by the audit store at ingest
  (`sequence_number`, `timestamp`, `ingest_time`, `prev_hash`, `event_hash`).
  Producers never assign these — this is what prevents independent producers
  from constructing competing hash chains.

`AuditEvent` is the full, persisted record (producer fields + server fields).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from emg_common_types import Classification, CorrelationId
from pydantic import BaseModel, ConfigDict, Field

AuditOutcome = Literal["success", "denied", "error"]
ActorType = Literal["human", "service"]

# Bound on free-form metadata to keep audit records small and prevent a
# producer from smuggling large or sensitive payloads into the store
# (validated in emg-audit-pipeline before persistence).
MAX_METADATA_ENTRIES = 32
MAX_METADATA_VALUE_LEN = 1024


class SubmittedAuditEvent(BaseModel):
    """The producer-supplied portion of an audit event — everything a service
    knows about a governed action *before* the central store assigns
    ordering, timing, and hash-chain fields.

    `event_id` is supplied by the producer and is the idempotency key: the
    store treats a repeated `event_id` as a duplicate and does not append a
    second record (US-04 / Sprint 6 "duplicate ingestion idempotent by
    event_id").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    actor: str
    actor_type: ActorType
    module: str
    action: str
    outcome: AuditOutcome
    correlation_id: CorrelationId | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    classification: Classification = Classification.INTERNAL
    source_system: str
    source_component: str | None = None
    reason: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    """A fully-persisted audit record: the producer's `SubmittedAuditEvent`
    fields plus the server-assigned ordering, timing, and hash-chain fields.

    Immutable by construction (`frozen=True`). No method on this model, and no
    method anywhere in `emg-audit-client` or `emg-audit-pipeline`, mutates a
    persisted event — see `docs/engineering/sprint-6-design.md`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- server-assigned ---
    event_id: str
    # The authenticated producer identity, assigned by the audit store from
    # the caller's validated service token — NEVER trusted from producer
    # event content. Idempotency is scoped to (source_principal, event_id), so
    # one producer cannot suppress another producer's event by reusing its
    # event_id (Sprint 6 security-review fix, Priority 5).
    source_principal: str
    sequence_number: int
    timestamp: datetime
    ingest_time: datetime
    prev_hash: str
    event_hash: str
    # --- producer-supplied ---
    actor: str
    actor_type: ActorType
    module: str
    action: str
    outcome: AuditOutcome
    correlation_id: CorrelationId | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    classification: Classification = Classification.INTERNAL
    source_system: str
    source_component: str | None = None
    reason: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
