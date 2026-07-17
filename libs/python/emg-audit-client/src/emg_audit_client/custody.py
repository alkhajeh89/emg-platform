"""Digital Evidence Chain-of-Custody models (Module 6 — Audit, Provenance &
Digital Evidence, FEAT-04-3, Sprint 7).

A custody ledger is a **separate append-only store** from the audit-event
store: it records the chain of custody for evidence items — who held an item,
who they received it from, when, and why. It is deliberately its own table and
its own hash chain, so introducing it does **not** touch, migrate, or re-hash
any existing Sprint 6 audit record.

Field ownership mirrors the audit event exactly:

- **Producer-supplied** fields describe the custody transfer (`evidence_id`,
  `custody_action`, `custodian`, `prior_custodian`, `transfer_reason`, ...). A
  producer builds a `SubmittedCustodyEvent`.
- **Server-assigned** fields are set centrally by the custody store at ingest
  (`source_principal`, `chain_sequence`, `custody_sequence`,
  `transfer_timestamp`, `ingest_time`, `prev_hash`, `event_hash`). A producer
  never supplies chain sequence, timestamps, hashes, or the source principal —
  they are not even fields on `SubmittedCustodyEvent`, so they cannot be forged
  (FEAT-04-3 integrity requirement).

Tamper-evidence uses the same SHA-256 hash-chain approach as FEAT-04-1 — **no
PKI or asymmetric signatures in Sprint 7, no new ADR** (Backlog FEAT-04-3
allows "digital signature *or* hash requirements").

This module defines the *shape* only; hashing, sequencing, integrity, and
persistence live in `emg-audit-pipeline`. See `docs/engineering/sprint-7-design.md`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from emg_common_types import Classification, CorrelationId
from pydantic import BaseModel, ConfigDict, Field

# The custody actions a transfer record can represent.
CustodyAction = Literal["acquire", "transfer", "hold", "release"]

# Bounds on custody free-text, validated in emg-audit-pipeline before
# persistence (same rationale as audit metadata/provenance bounds).
MAX_CUSTODY_VALUE_LEN = 1024


class SubmittedCustodyEvent(BaseModel):
    """The producer-supplied portion of a custody transfer — everything known
    about a custody event *before* the central store assigns ordering, timing,
    and hash-chain fields.

    `custody_event_id` is the idempotency key: the store treats a repeated
    `(source_principal, custody_event_id)` as a duplicate and does not append a
    second record, while two different producers using the same
    `custody_event_id` create distinct events (mirrors the Sprint 6 P5
    per-principal idempotency fix).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    custody_event_id: str
    evidence_id: str
    custody_action: CustodyAction
    custodian: str
    prior_custodian: str | None = None
    transfer_reason: str = ""
    classification: Classification = Classification.INTERNAL
    correlation_id: CorrelationId | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class CustodyEvent(BaseModel):
    """A fully-persisted custody record: the producer's `SubmittedCustodyEvent`
    fields plus the server-assigned ordering, timing, and hash-chain fields.

    Immutable by construction (`frozen=True`). No method mutates a persisted
    custody record — append-only is a property of the contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- server-assigned ---
    custody_event_id: str
    # The authenticated producer identity, assigned by the custody store from
    # the caller's validated service token — NEVER from producer content.
    source_principal: str
    # Global monotonic sequence across the whole custody ledger (single-writer
    # chain), used for the global hash chain + ordering.
    chain_sequence: int
    # Per-evidence monotonic sequence (1, 2, 3, … within one evidence_id), used
    # for per-evidence gap detection.
    custody_sequence: int
    transfer_timestamp: datetime
    ingest_time: datetime
    prev_hash: str
    event_hash: str
    # --- producer-supplied ---
    evidence_id: str
    custody_action: CustodyAction
    custodian: str
    prior_custodian: str | None = None
    transfer_reason: str = ""
    classification: Classification = Classification.INTERNAL
    correlation_id: CorrelationId | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class CustodyQuery(BaseModel):
    """Filter for reading custody events. All fields optional; filters combine
    with AND. `start_time`/`end_time` bound `CustodyEvent.transfer_timestamp`,
    inclusive of `start_time` and exclusive of `end_time`.

    Sprint 7 (FEAT-04-3) shipped the minimal retrieval surface (by evidence
    item / custodian / time range). Sprint 8 (FEAT-04-4) adds — additively and
    backward-compatibly — a `classification` filter and an opaque `cursor` for
    stable keyset pagination over `chain_sequence` (unique + monotonic, so no
    duplicates and no skipped records). `classification` is a filter dimension
    only, not clearance-based access enforcement (see query.py).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str | None = None
    custodian: str | None = None
    classification: Classification | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    cursor: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
