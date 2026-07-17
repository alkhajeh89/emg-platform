"""The AuditQuery model.

Sprint 6 (FEAT-04-1) shipped the minimal US-04 surface: filter by actor, time
range, and correlation identifier. Sprint 8 (FEAT-04-4, Audit Query & Reporting
Interface) extends it — additively and backward-compatibly — with the richer
filter dimensions the reporting interface needs (module, action, outcome,
source system, classification, provenance-presence) and an opaque `cursor` for
stable keyset pagination.

Every field remains optional with a Sprint 6-compatible default, so an existing
caller that only sets `actor`/`start_time`/`end_time`/`correlation_id`/`limit`
behaves exactly as before. Filters combine with AND.

Note on classification (FEAT-04-4 scope, Sprint 8): `classification` here is a
*filter* dimension only — callers may narrow results to a classification. It is
NOT clearance-based access enforcement; classification-aware read *authorization*
(restricting which classifications a principal may see) is a deliberate
follow-up that needs a human reader role and an authorization decision (see
`docs/engineering/security-limitations.md`).
"""

from __future__ import annotations

from datetime import datetime

from emg_common_types import Classification, CorrelationId
from pydantic import BaseModel, ConfigDict, Field

from .event import AuditOutcome


class AuditQuery(BaseModel):
    """Filter for reading audit events. All fields optional; an all-None query
    returns events from the start of the chain up to `limit`, ordered by
    `sequence_number` ascending. Filters combine with AND.

    `start_time`/`end_time` bound `AuditEvent.timestamp` (the server-assigned
    UTC capture time), inclusive of `start_time` and exclusive of `end_time`.

    `cursor` is an opaque keyset-pagination token (see
    `emg_audit_pipeline.pagination`): when set, only events strictly after the
    cursor position (by `sequence_number`) are returned. Because
    `sequence_number` is unique and monotonic, cursor paging yields a stable
    ordering with no duplicates and no skipped records.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Sprint 6 (FEAT-04-1) minimal US-04 surface ---
    actor: str | None = None
    correlation_id: CorrelationId | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    # --- Sprint 8 (FEAT-04-4) richer filter dimensions ---
    module: str | None = None
    action: str | None = None
    outcome: AuditOutcome | None = None
    source_system: str | None = None
    classification: Classification | None = None
    # Filter by whether an event carries a provenance record (FEAT-04-2). This
    # is the coherent, scalar "filter by provenance" dimension; deep filtering
    # on individual provenance sub-fields is deferred (see sprint-8-design.md).
    has_provenance: bool | None = None
    # --- pagination ---
    cursor: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
