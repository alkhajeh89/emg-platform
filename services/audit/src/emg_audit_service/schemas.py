"""HTTP response models for the audit service (Sprint 6).

The ingest request body is `emg_audit_client.SubmittedAuditEvent` directly
(no separate DTO). Responses expose the safe, persisted fields; there is no
response field that could carry a secret or token (those are rejected/redacted
before persistence by `emg-audit-pipeline`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IngestResponse(BaseModel):
    """Acknowledgement that an event was durably appended (or already
    present, for an idempotent duplicate)."""

    event_id: str
    sequence_number: int
    event_hash: str
    accepted: bool = True


class AuditEventView(BaseModel):
    """Read view of a persisted audit event for the minimal US-04 query."""

    event_id: str
    source_principal: str
    sequence_number: int
    timestamp: datetime
    correlation_id: str | None
    actor: str
    actor_type: str
    module: str
    action: str
    outcome: str
    resource_type: str | None
    resource_id: str | None
    classification: str
    source_system: str
    reason: str


class CustodyIngestResponse(BaseModel):
    """Acknowledgement that a custody transfer was durably appended (or already
    present, for an idempotent duplicate) — FEAT-04-3."""

    custody_event_id: str
    chain_sequence: int
    custody_sequence: int
    event_hash: str
    accepted: bool = True


class CustodyEventView(BaseModel):
    """Read view of a persisted custody event (FEAT-04-3). Exposes safe,
    persisted fields only; no field can carry a secret (rejected/redacted
    before persistence)."""

    custody_event_id: str
    source_principal: str
    chain_sequence: int
    custody_sequence: int
    transfer_timestamp: datetime
    evidence_id: str
    custody_action: str
    custodian: str
    prior_custodian: str | None
    transfer_reason: str
    classification: str
    correlation_id: str | None


class AuditEventPage(BaseModel):
    """A cursor-paginated page of audit events (FEAT-04-4). `next_cursor` is an
    opaque token to pass back for the following page; it is null when the last
    page has been reached. `count` is the number of items in this page."""

    items: list[AuditEventView]
    next_cursor: str | None = None
    count: int


class CustodyEventPage(BaseModel):
    """A cursor-paginated page of custody events (FEAT-04-4)."""

    items: list[CustodyEventView]
    next_cursor: str | None = None
    count: int


class IntegrityResponse(BaseModel):
    intact: bool
    checked_count: int
    first_broken_sequence: int | None
    detail: str


class ReadinessResponse(BaseModel):
    status: str
    store_backend: str
    store_available: bool
    detail: str
