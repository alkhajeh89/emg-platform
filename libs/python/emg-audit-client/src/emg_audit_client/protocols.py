"""The audit contracts every service programs against (FEAT-04-1).

Two structural `Protocol`s, analogous to `emg_auth_client`'s
`PolicyEnforcementPoint`:

- `AuditSink` — what a *producer* service depends on to record a governed
  action. `services/identity`'s `PipelineAuditSink` and the audit service's
  own ingestion both satisfy it. The sink takes a `SubmittedAuditEvent` (the
  producer's portion) and is responsible for durability semantics
  (delivery / spool / dead-letter — Sprint 6 Decision C).
- `AuditEventStore` — the append-only system-of-record. It assigns the
  central `sequence_number`, timing, and hash-chain fields, returning the
  fully-persisted `AuditEvent`. Implemented by `InMemoryAuditEventStore`
  (tests) and `PostgresAuditEventStore` (tier-1) in `emg-audit-pipeline`.

There is deliberately no `update`/`delete` method on either protocol —
append-only is a property of the contract, not just the implementation
(US-04: "no code path can delete or mutate a published event").
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .custody import CustodyEvent, CustodyQuery, SubmittedCustodyEvent
from .event import AuditEvent, SubmittedAuditEvent
from .query import AuditQuery


@runtime_checkable
class AuditSink(Protocol):
    """A producer-facing sink for recording governed actions."""

    def record(self, event: SubmittedAuditEvent) -> None:
        """Record a governed action. Implementations define durability
        behavior (e.g. deliver-then-spool-then-dead-letter); this method must
        never raise merely because a remote store is temporarily
        unavailable (Sprint 6 compatibility posture), and must never silently
        claim success it cannot guarantee."""
        ...


@runtime_checkable
class AuditEventStore(Protocol):
    """The append-only audit system-of-record."""

    def append(self, event: SubmittedAuditEvent, *, source_principal: str) -> AuditEvent:
        """Append one event and return the fully-persisted record with
        server-assigned `source_principal`, `sequence_number`, `timestamp`,
        `ingest_time`, and hash-chain fields.

        `source_principal` is the authenticated producer identity, assigned by
        the caller (the audit service) from the validated service token — never
        taken from producer content. Idempotency is scoped to
        `(source_principal, event_id)`: re-appending an event whose
        `(source_principal, event_id)` already exists returns the existing
        record without appending a duplicate, but two different producers using
        the same `event_id` create distinct events (Sprint 6 security-review
        fix, Priority 5)."""
        ...

    def query(self, query: AuditQuery) -> list[AuditEvent]:
        """Return events matching `query`, ordered by `sequence_number`."""
        ...

    def verify_integrity(self) -> IntegrityResult:
        """Recompute the hash chain over all stored events and report whether
        it is intact (out-of-band mutation detection)."""
        ...


@runtime_checkable
class CustodyEventStore(Protocol):
    """The append-only digital-evidence chain-of-custody ledger (FEAT-04-3).

    A separate store from `AuditEventStore` — its own table and its own hash
    chain — so it never mutates or re-hashes an audit event. Same single-writer
    discipline: the store assigns `source_principal`, the global
    `chain_sequence`, the per-evidence `custody_sequence`, timing, and the
    hash-chain fields centrally.
    """

    def append(self, event: SubmittedCustodyEvent, *, source_principal: str) -> CustodyEvent:
        """Append one custody transfer and return the fully-persisted record.

        Idempotency is scoped to `(source_principal, custody_event_id)`:
        re-appending an event whose key already exists returns the existing
        record without appending a duplicate, while two different producers
        using the same `custody_event_id` create distinct events.
        `source_principal` is assigned by the caller from the validated service
        token — never from producer content."""
        ...

    def query(self, query: CustodyQuery) -> list[CustodyEvent]:
        """Return custody events matching `query`, ordered by
        `chain_sequence`."""
        ...

    def verify_integrity(self) -> IntegrityResult:
        """Recompute the global custody hash chain and check per-evidence
        sequence contiguity; report tamper, deletion, sequence gaps, and
        schema-violating rows as an explicit failure result — never a raised
        500 (FEAT-04-3 integrity requirement)."""
        ...


class IntegrityResult(Protocol):
    """Result of `AuditEventStore.verify_integrity` /
    `CustodyEventStore.verify_integrity`. `intact` is True when the recomputed
    hash chain matches every stored hash (and, for custody, per-evidence
    sequences are contiguous); when False, `first_broken_sequence` is the
    earliest sequence number whose verification fails."""

    @property
    def intact(self) -> bool: ...

    @property
    def checked_count(self) -> int: ...

    @property
    def first_broken_sequence(self) -> int | None: ...

    @property
    def detail(self) -> str: ...
