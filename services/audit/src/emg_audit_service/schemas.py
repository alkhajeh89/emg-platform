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
