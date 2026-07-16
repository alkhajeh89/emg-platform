"""Append-only digital-evidence chain-of-custody stores (FEAT-04-3, Sprint 7).

Two implementations of `emg_audit_client.CustodyEventStore`, mirroring the
Sprint 6 audit stores:

- `InMemoryCustodyEventStore` — tests / local development.
- `PostgresCustodyEventStore` — tier-1, backed by the append-only
  `evidence_custody_events` table (`tools/seed-data/postgres/003_evidence_custody.sql`);
  INSERT/SELECT-only application role, no application UPDATE/DELETE path.

The custody ledger is a **separate** store from the audit-event store — its own
table and its own hash chain — so it never touches, migrates, or re-hashes any
Sprint 6 audit record.

**Centralized single-writer chain.** The store assigns `source_principal`, the
global `chain_sequence`, the per-evidence `custody_sequence`, timing, and the
hash-chain link; producers supply none of these (they are not fields on
`SubmittedCustodyEvent`). Postgres appends serialize on a dedicated
transaction-level advisory lock, with `UNIQUE(chain_sequence)` as
defense-in-depth and a bounded retry, exactly like the audit chain.

**Integrity** detects mutation, deletion, global-chain sequence gaps,
per-evidence custody-sequence gaps, and schema-violating stored rows — and
returns an explicit failure result, never a raised 500.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from emg_audit_client import (
    MAX_CUSTODY_VALUE_LEN,
    MAX_METADATA_ENTRIES,
    MAX_METADATA_VALUE_LEN,
    CustodyEvent,
    CustodyQuery,
    SubmittedCustodyEvent,
)
from emg_errors import ValidationError

from .custody_hashing import GENESIS_PREV_HASH, compute_custody_hash, recompute_custody_event_hash
from .integrity import IntegrityReport
from .validation import is_sensitive_key, redact_text

if TYPE_CHECKING:
    from psycopg import Connection


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_and_sanitize_custody(event: SubmittedCustodyEvent) -> SubmittedCustodyEvent:
    """Validate and redact a custody event before persistence (FEAT-04-3),
    same posture as audit events: bound `transfer_reason` and metadata, reject
    sensitive metadata keys, and redact secret-shaped substrings."""
    if len(event.transfer_reason) > MAX_CUSTODY_VALUE_LEN:
        raise ValidationError(
            f"custody transfer_reason is {len(event.transfer_reason)} chars; "
            f"maximum is {MAX_CUSTODY_VALUE_LEN}",
            error_code="CUSTODY_REASON_TOO_LONG",
        )
    if len(event.metadata) > MAX_METADATA_ENTRIES:
        raise ValidationError(
            f"custody metadata has {len(event.metadata)} entries; "
            f"maximum is {MAX_METADATA_ENTRIES}",
            error_code="CUSTODY_METADATA_TOO_LARGE",
        )
    for key, value in event.metadata.items():
        if is_sensitive_key(key):
            raise ValidationError(
                f"custody metadata key {key!r} looks sensitive and may not be stored",
                error_code="CUSTODY_METADATA_SENSITIVE_KEY",
            )
        if len(value) > MAX_METADATA_VALUE_LEN:
            raise ValidationError(
                f"custody metadata value for {key!r} is {len(value)} chars; "
                f"maximum is {MAX_METADATA_VALUE_LEN}",
                error_code="CUSTODY_METADATA_VALUE_TOO_LONG",
            )
    sanitized_metadata = {key: redact_text(value) for key, value in event.metadata.items()}
    return event.model_copy(
        update={
            "transfer_reason": redact_text(event.transfer_reason),
            "metadata": sanitized_metadata,
        }
    )


def _build_persisted_custody_event(
    submitted: SubmittedCustodyEvent,
    *,
    source_principal: str,
    chain_sequence: int,
    custody_sequence: int,
    prev_hash: str,
    now: datetime | None = None,
) -> CustodyEvent:
    """Centralized construction of a persisted `CustodyEvent`: assigns the
    server-side identity, global + per-evidence sequences, timing, and the
    hash-chain link. Shared by both stores."""
    transfer_timestamp = now or _utcnow()
    event_hash = compute_custody_hash(
        custody_event_id=submitted.custody_event_id,
        source_principal=source_principal,
        chain_sequence=chain_sequence,
        custody_sequence=custody_sequence,
        transfer_timestamp=transfer_timestamp,
        ingest_time=transfer_timestamp,
        submitted=submitted,
        prev_hash=prev_hash,
    )
    return CustodyEvent(
        custody_event_id=submitted.custody_event_id,
        source_principal=source_principal,
        chain_sequence=chain_sequence,
        custody_sequence=custody_sequence,
        transfer_timestamp=transfer_timestamp,
        ingest_time=transfer_timestamp,
        prev_hash=prev_hash,
        event_hash=event_hash,
        evidence_id=submitted.evidence_id,
        custody_action=submitted.custody_action,
        custodian=submitted.custodian,
        prior_custodian=submitted.prior_custodian,
        transfer_reason=submitted.transfer_reason,
        classification=submitted.classification,
        correlation_id=submitted.correlation_id,
        metadata=submitted.metadata,
    )


def _matches(event: CustodyEvent, query: CustodyQuery) -> bool:
    if query.evidence_id is not None and event.evidence_id != query.evidence_id:
        return False
    if query.custodian is not None and event.custodian != query.custodian:
        return False
    if query.start_time is not None and event.transfer_timestamp < query.start_time:
        return False
    return not (query.end_time is not None and event.transfer_timestamp >= query.end_time)


def verify_custody_chain(events: list[CustodyEvent]) -> IntegrityReport:
    """Verify the global custody hash chain over `events` (assumed ordered by
    `chain_sequence`) **and** per-evidence `custody_sequence` contiguity.

    Detects, as an explicit `IntegrityReport` (never a raised exception):
    a mutated field (hash mismatch), a broken chain link, a global-chain
    sequence that is not strictly increasing (reordering / deleted event), a
    schema-violating stored record, and a per-evidence custody-sequence gap
    (a deleted middle transfer for an evidence item)."""
    prev_hash = GENESIS_PREV_HASH
    prev_sequence: int | None = None
    per_evidence: dict[str, list[int]] = {}

    for event in events:
        if prev_sequence is not None and event.chain_sequence <= prev_sequence:
            return IntegrityReport(
                intact=False,
                checked_count=event.chain_sequence,
                first_broken_sequence=event.chain_sequence,
                detail=(
                    f"custody chain_sequence not strictly increasing at "
                    f"{event.chain_sequence} (previous {prev_sequence})"
                ),
            )
        if event.prev_hash != prev_hash:
            return IntegrityReport(
                intact=False,
                checked_count=event.chain_sequence,
                first_broken_sequence=event.chain_sequence,
                detail=f"broken custody chain link at chain_sequence {event.chain_sequence}",
            )
        try:
            expected = recompute_custody_event_hash(event)
        except Exception as exc:
            return IntegrityReport(
                intact=False,
                checked_count=event.chain_sequence,
                first_broken_sequence=event.chain_sequence,
                detail=(
                    f"stored custody record at chain_sequence {event.chain_sequence} could "
                    f"not be re-hashed (schema-violating tamper): {exc}"
                ),
            )
        if expected != event.event_hash:
            return IntegrityReport(
                intact=False,
                checked_count=event.chain_sequence,
                first_broken_sequence=event.chain_sequence,
                detail=(
                    f"custody hash mismatch at chain_sequence {event.chain_sequence} "
                    "(record mutated)"
                ),
            )
        per_evidence.setdefault(event.evidence_id, []).append(event.custody_sequence)
        prev_hash = event.event_hash
        prev_sequence = event.chain_sequence

    # Per-evidence gap detection: each evidence item's custody_sequence values
    # must form a contiguous 1..N run (a deleted middle transfer leaves a gap).
    for evidence_id, sequences in per_evidence.items():
        ordered = sorted(sequences)
        expected_run = list(range(1, len(ordered) + 1))
        if ordered != expected_run:
            return IntegrityReport(
                intact=False,
                checked_count=len(events),
                first_broken_sequence=None,
                detail=(
                    f"custody sequence gap for evidence {evidence_id!r}: "
                    f"expected contiguous {expected_run}, found {ordered}"
                ),
            )

    return IntegrityReport(
        intact=True,
        checked_count=len(events),
        first_broken_sequence=None,
        detail="custody chain intact",
    )


class InMemoryCustodyEventStore:
    """Append-only in-process custody ledger for tests and local development."""

    def __init__(self) -> None:
        self._events: list[CustodyEvent] = []
        # Idempotency scoped to (source_principal, custody_event_id) — P5 posture.
        self._by_key: dict[tuple[str, str], CustodyEvent] = {}
        # Per-evidence custody sequence counter.
        self._evidence_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def append(self, event: SubmittedCustodyEvent, *, source_principal: str) -> CustodyEvent:
        sanitized = validate_and_sanitize_custody(event)
        with self._lock:
            key = (source_principal, sanitized.custody_event_id)
            existing = self._by_key.get(key)
            if existing is not None:
                return existing  # idempotent by (source_principal, custody_event_id)
            chain_sequence = len(self._events) + 1
            custody_sequence = self._evidence_counts.get(sanitized.evidence_id, 0) + 1
            prev_hash = self._events[-1].event_hash if self._events else GENESIS_PREV_HASH
            persisted = _build_persisted_custody_event(
                sanitized,
                source_principal=source_principal,
                chain_sequence=chain_sequence,
                custody_sequence=custody_sequence,
                prev_hash=prev_hash,
            )
            self._events.append(persisted)
            self._by_key[key] = persisted
            self._evidence_counts[sanitized.evidence_id] = custody_sequence
            return persisted

    def query(self, query: CustodyQuery) -> list[CustodyEvent]:
        with self._lock:
            matched = [event for event in self._events if _matches(event, query)]
        return matched[: query.limit]

    def verify_integrity(self) -> IntegrityReport:
        with self._lock:
            snapshot = list(self._events)
        return verify_custody_chain(snapshot)

    # Test-only helper: simulate out-of-band mutation/deletion to prove the
    # integrity verifier detects it. NOT part of the CustodyEventStore contract.
    def _unsafe_replace_for_tamper_test(self, index: int, event: CustodyEvent) -> None:
        with self._lock:
            self._events[index] = event
            self._by_key[(event.source_principal, event.custody_event_id)] = event

    def _unsafe_delete_for_tamper_test(self, index: int) -> None:
        with self._lock:
            removed = self._events.pop(index)
            self._by_key.pop((removed.source_principal, removed.custody_event_id), None)


class PostgresCustodyEventStore:
    """Append-only PostgreSQL custody ledger (tier-1). INSERT + SELECT only.

    Appends serialize on a dedicated transaction-level advisory lock (distinct
    from the audit chain's), acquired before the chain tail is read and held
    until commit, so concurrent appends cannot compute the same next
    `chain_sequence`. `UNIQUE(chain_sequence)` is defense-in-depth; a bounded
    retry absorbs the rare conflict so an append never surfaces an unhandled
    500. Idempotency is scoped to `(source_principal, custody_event_id)`.
    """

    _TABLE = "evidence_custody_events"
    # Fixed 32-bit key ("CUST") for the custody chain advisory lock — distinct
    # from the audit chain's 0x41554449 ("AUDI").
    _CHAIN_ADVISORY_LOCK_KEY = 0x43555354
    _MAX_APPEND_ATTEMPTS = 5

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def append(self, event: SubmittedCustodyEvent, *, source_principal: str) -> CustodyEvent:
        sanitized = validate_and_sanitize_custody(event)
        import time

        import psycopg

        last_exc: Exception | None = None
        for attempt in range(self._MAX_APPEND_ATTEMPTS):
            try:
                return self._append_once(sanitized, source_principal)
            except (
                psycopg.errors.SerializationFailure,
                psycopg.errors.UniqueViolation,
                psycopg.errors.DeadlockDetected,
            ) as exc:
                self._conn.rollback()
                last_exc = exc
                time.sleep(0.02 * (2**attempt))
        assert last_exc is not None
        raise last_exc

    def _append_once(self, sanitized: SubmittedCustodyEvent, source_principal: str) -> CustodyEvent:
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (self._CHAIN_ADVISORY_LOCK_KEY,))

            cur.execute(
                f"SELECT 1 FROM {self._TABLE} "
                "WHERE source_principal = %s AND custody_event_id = %s",
                (source_principal, sanitized.custody_event_id),
            )
            if cur.fetchone() is not None:
                self._conn.commit()
                return self._fetch_by_key(source_principal, sanitized.custody_event_id)

            cur.execute(
                f"SELECT chain_sequence, event_hash FROM {self._TABLE} "
                "ORDER BY chain_sequence DESC LIMIT 1"
            )
            tail = cur.fetchone()
            if tail is None:
                chain_sequence = 1
                prev_hash = GENESIS_PREV_HASH
            else:
                chain_sequence = int(cast(int, tail[0])) + 1
                prev_hash = str(tail[1])

            cur.execute(
                f"SELECT COALESCE(MAX(custody_sequence), 0) FROM {self._TABLE} "
                "WHERE evidence_id = %s",
                (sanitized.evidence_id,),
            )
            max_row = cur.fetchone()
            custody_sequence = int(cast(int, max_row[0])) + 1 if max_row is not None else 1

            persisted = _build_persisted_custody_event(
                sanitized,
                source_principal=source_principal,
                chain_sequence=chain_sequence,
                custody_sequence=custody_sequence,
                prev_hash=prev_hash,
            )
            cur.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    custody_event_id, source_principal, chain_sequence, custody_sequence,
                    transfer_timestamp, ingest_time, prev_hash, event_hash, evidence_id,
                    custody_action, custodian, prior_custodian, transfer_reason,
                    classification, correlation_id, metadata
                ) VALUES (
                    %(custody_event_id)s, %(source_principal)s, %(chain_sequence)s,
                    %(custody_sequence)s, %(transfer_timestamp)s, %(ingest_time)s,
                    %(prev_hash)s, %(event_hash)s, %(evidence_id)s, %(custody_action)s,
                    %(custodian)s, %(prior_custodian)s, %(transfer_reason)s,
                    %(classification)s, %(correlation_id)s, %(metadata)s
                )
                ON CONFLICT (source_principal, custody_event_id) DO NOTHING
                """,
                self._row_params(persisted),
            )
            self._conn.commit()
            return self._fetch_by_key(source_principal, persisted.custody_event_id)

    def query(self, query: CustodyQuery) -> list[CustodyEvent]:
        clauses: list[str] = []
        params: dict[str, object] = {}
        if query.evidence_id is not None:
            clauses.append("evidence_id = %(evidence_id)s")
            params["evidence_id"] = query.evidence_id
        if query.custodian is not None:
            clauses.append("custodian = %(custodian)s")
            params["custodian"] = query.custodian
        if query.start_time is not None:
            clauses.append("transfer_timestamp >= %(start_time)s")
            params["start_time"] = query.start_time
        if query.end_time is not None:
            clauses.append("transfer_timestamp < %(end_time)s")
            params["end_time"] = query.end_time
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params["limit"] = query.limit
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._COLUMNS} FROM {self._TABLE} {where} "
                "ORDER BY chain_sequence ASC LIMIT %(limit)s",
                params,
            )
            return [self._row_to_event(row) for row in cur.fetchall()]

    def verify_integrity(self) -> IntegrityReport:
        """Defensively parse each stored row before verification; a row that no
        longer parses into a valid `CustodyEvent` is reported as a failure at
        its raw `chain_sequence`, never a raised 500."""
        events: list[CustodyEvent] = []
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT {self._COLUMNS} FROM {self._TABLE} ORDER BY chain_sequence ASC")
            for row in cur.fetchall():
                try:
                    events.append(self._row_to_event(row))
                except Exception as exc:
                    raw_seq = self._raw_sequence(row)
                    return IntegrityReport(
                        intact=False,
                        checked_count=len(events),
                        first_broken_sequence=raw_seq,
                        detail=(
                            f"stored custody record at chain_sequence {raw_seq} failed to "
                            f"parse (schema-violating tamper): {exc}"
                        ),
                    )
        return verify_custody_chain(events)

    @staticmethod
    def _raw_sequence(row: tuple[object, ...]) -> int | None:
        try:
            return int(cast(int, row[2]))  # chain_sequence column (see _COLUMNS)
        except Exception:  # pragma: no cover - defensive
            return None

    _COLUMNS = (
        "custody_event_id, source_principal, chain_sequence, custody_sequence, "
        "transfer_timestamp, ingest_time, prev_hash, event_hash, evidence_id, "
        "custody_action, custodian, prior_custodian, transfer_reason, classification, "
        "correlation_id, metadata"
    )

    def _fetch_by_key(self, source_principal: str, custody_event_id: str) -> CustodyEvent:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._COLUMNS} FROM {self._TABLE} "
                "WHERE source_principal = %s AND custody_event_id = %s",
                (source_principal, custody_event_id),
            )
            row = cur.fetchone()
        if row is None:  # pragma: no cover - defensive
            raise RuntimeError(
                f"custody event {custody_event_id!r} not found immediately after insert"
            )
        return self._row_to_event(row)

    @staticmethod
    def _row_params(event: CustodyEvent) -> dict[str, object]:
        import json

        return {
            "custody_event_id": event.custody_event_id,
            "source_principal": event.source_principal,
            "chain_sequence": event.chain_sequence,
            "custody_sequence": event.custody_sequence,
            "transfer_timestamp": event.transfer_timestamp,
            "ingest_time": event.ingest_time,
            "prev_hash": event.prev_hash,
            "event_hash": event.event_hash,
            "evidence_id": event.evidence_id,
            "custody_action": event.custody_action,
            "custodian": event.custodian,
            "prior_custodian": event.prior_custodian,
            "transfer_reason": event.transfer_reason,
            "classification": event.classification.value,
            "correlation_id": event.correlation_id,
            "metadata": json.dumps(event.metadata),
        }

    @staticmethod
    def _row_to_event(row: tuple[object, ...]) -> CustodyEvent:
        import json

        from emg_common_types import Classification

        raw_metadata = row[15]
        metadata = raw_metadata if isinstance(raw_metadata, dict) else json.loads(str(raw_metadata))
        return CustodyEvent(
            custody_event_id=str(row[0]),
            source_principal=str(row[1]),
            chain_sequence=int(cast(int, row[2])),
            custody_sequence=int(cast(int, row[3])),
            transfer_timestamp=cast(datetime, row[4]),
            ingest_time=cast(datetime, row[5]),
            prev_hash=str(row[6]),
            event_hash=str(row[7]),
            evidence_id=str(row[8]),
            custody_action=row[9],  # type: ignore[arg-type]
            custodian=str(row[10]),
            prior_custodian=None if row[11] is None else str(row[11]),
            transfer_reason=str(row[12]),
            classification=Classification(str(row[13])),
            correlation_id=None if row[14] is None else str(row[14]),
            metadata=metadata,
        )
