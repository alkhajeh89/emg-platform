"""Append-only audit event stores (FEAT-04-1).

Two implementations of `emg_audit_client.AuditEventStore`:

- `InMemoryAuditEventStore` — for tests and local development; an append-only
  in-process list.
- `PostgresAuditEventStore` — the tier-1 system-of-record, backed by the
  append-only `audit_events` table (see
  `tools/seed-data/postgres/001_audit_events.sql`). The application role has
  INSERT and SELECT privileges only — there is no application UPDATE or DELETE
  path.

**Centralized sequencing and hashing.** Both stores assign the
`sequence_number`, `timestamp`, `ingest_time`, `prev_hash`, and `event_hash`
themselves, via the shared `_build_persisted_event` helper. Producer services
never assign these, so independent producers cannot construct competing hash
chains — the chain is single-writer per store (Sprint 6 approved requirement).

**Append-only and immutability** are properties of the contract: neither store
exposes an update or delete method. For Postgres this is additionally enforced
by database role grants; the hash chain makes any out-of-band mutation
detectable via `verify_integrity` (the honest limitation being that a
database superuser can still alter storage — which the chain is designed to
*detect*, see `docs/engineering/sprint-6-design.md`).

**Idempotency.** `append` is idempotent by `event_id`: re-appending an event
whose id already exists returns the existing persisted record without adding a
duplicate.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from emg_audit_client import (
    EVENT_SCHEMA_VERSION_V1,
    EVENT_SCHEMA_VERSION_V2,
    EVENT_SCHEMA_VERSION_V3,
    AuditEvent,
    AuditQuery,
    SubmittedAuditEvent,
)

from .hashing import GENESIS_PREV_HASH, compute_hash
from .integrity import IntegrityReport, verify_chain
from .pagination import decode_cursor
from .validation import validate_and_sanitize

if TYPE_CHECKING:
    from psycopg import Connection


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _build_persisted_event(
    submitted: SubmittedAuditEvent,
    *,
    source_principal: str,
    tenant_id: str | None,
    sequence_number: int,
    prev_hash: str,
    now: datetime | None = None,
) -> AuditEvent:
    """Centralized construction of a persisted `AuditEvent` from a producer's
    `SubmittedAuditEvent`: assigns the server-side `source_principal`,
    `schema_version`, timing, and the hash-chain link. Shared by every store so
    the chaining logic is identical everywhere.

    `schema_version` is derived *server-side* from the presence of provenance
    (FEAT-04-2): an event with a `ProvenanceRecord` is version 2 (provenance is
    hashed), one without is version 1 (byte-for-byte hash-compatible with Sprint
    6). A producer cannot set the version directly."""
    timestamp = now or _utcnow()
    schema_version = (
        EVENT_SCHEMA_VERSION_V3
        if tenant_id is not None
        else (
            EVENT_SCHEMA_VERSION_V2 if submitted.provenance is not None else EVENT_SCHEMA_VERSION_V1
        )
    )
    event_hash = compute_hash(
        event_id=submitted.event_id,
        source_principal=source_principal,
        sequence_number=sequence_number,
        timestamp=timestamp,
        ingest_time=timestamp,
        submitted=submitted,
        prev_hash=prev_hash,
        schema_version=schema_version,
        tenant_id=tenant_id,
    )
    return AuditEvent(
        event_id=submitted.event_id,
        source_principal=source_principal,
        tenant_id=tenant_id,
        sequence_number=sequence_number,
        schema_version=schema_version,
        timestamp=timestamp,
        ingest_time=timestamp,
        prev_hash=prev_hash,
        event_hash=event_hash,
        actor=submitted.actor,
        actor_type=submitted.actor_type,
        module=submitted.module,
        action=submitted.action,
        outcome=submitted.outcome,
        correlation_id=submitted.correlation_id,
        resource_type=submitted.resource_type,
        resource_id=submitted.resource_id,
        classification=submitted.classification,
        source_system=submitted.source_system,
        source_component=submitted.source_component,
        reason=submitted.reason,
        metadata=submitted.metadata,
        provenance=submitted.provenance,
    )


def _matches(event: AuditEvent, query: AuditQuery) -> bool:
    if query.tenant_id is not None and event.tenant_id != query.tenant_id:
        return False
    if query.event_id is not None and event.event_id != query.event_id:
        return False
    if (
        query.allowed_classifications is not None
        and event.classification not in query.allowed_classifications
    ):
        return False
    # Sprint 6 (FEAT-04-1) filters.
    if query.actor is not None and event.actor != query.actor:
        return False
    if query.correlation_id is not None and event.correlation_id != query.correlation_id:
        return False
    if query.start_time is not None and event.timestamp < query.start_time:
        return False
    if query.end_time is not None and event.timestamp >= query.end_time:
        return False
    # Sprint 8 (FEAT-04-4) richer filters.
    if query.module is not None and event.module != query.module:
        return False
    if query.action is not None and event.action != query.action:
        return False
    if query.outcome is not None and event.outcome != query.outcome:
        return False
    if query.source_system is not None and event.source_system != query.source_system:
        return False
    if query.classification is not None and event.classification != query.classification:
        return False
    return not (
        query.has_provenance is not None and (event.provenance is not None) != query.has_provenance
    )


class InMemoryAuditEventStore:
    """Append-only in-process store for tests and local development."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        # Idempotency is scoped to (source_principal, event_id) so one producer
        # cannot suppress another's event by reusing its event_id (P5).
        self._by_key: dict[tuple[str, str], AuditEvent] = {}
        self._lock = threading.Lock()

    def append(
        self,
        event: SubmittedAuditEvent,
        *,
        source_principal: str,
        tenant_id: str | None = None,
    ) -> AuditEvent:
        sanitized = validate_and_sanitize(event)
        with self._lock:
            key = (source_principal, sanitized.event_id)
            existing = self._by_key.get(key)
            if existing is not None:
                return existing  # idempotent by (source_principal, event_id)
            sequence_number = len(self._events) + 1
            prev_hash = self._events[-1].event_hash if self._events else GENESIS_PREV_HASH
            persisted = _build_persisted_event(
                sanitized,
                source_principal=source_principal,
                tenant_id=tenant_id,
                sequence_number=sequence_number,
                prev_hash=prev_hash,
            )
            self._events.append(persisted)
            self._by_key[key] = persisted
            return persisted

    def query(self, query: AuditQuery) -> list[AuditEvent]:
        after = decode_cursor(query.cursor) if query.cursor is not None else None
        with self._lock:
            matched = [
                event
                for event in self._events
                if _matches(event, query) and (after is None or event.sequence_number > after)
            ]
        # self._events is in append order == ascending sequence_number, so the
        # slice is a deterministic keyset page (no duplicates, no skips).
        return matched[: query.limit]

    def verify_integrity(self) -> IntegrityReport:
        with self._lock:
            snapshot = list(self._events)
        return verify_chain(snapshot)

    # Test-only helper: simulate out-of-band mutation to prove the integrity
    # verifier detects it. NOT part of the AuditEventStore contract and never
    # used by the service — the store exposes no mutation path in production.
    def _unsafe_replace_for_tamper_test(self, index: int, event: AuditEvent) -> None:
        with self._lock:
            self._events[index] = event
            self._by_key[(event.source_principal, event.event_id)] = event


class PostgresAuditEventStore:
    """Append-only PostgreSQL system-of-record (tier-1).

    Uses only INSERT and SELECT — matching the INSERT/SELECT-only grants on
    the application role.

    **Serialization (Sprint 6 security-review fix, Priority 1).** Appends are
    serialized by a *transaction-level PostgreSQL advisory lock* dedicated to
    the audit chain (`pg_advisory_xact_lock`), acquired before the chain tail is
    read and held (released automatically at commit/rollback) until the new row
    is inserted. This makes the tail-read → sequence/prev_hash assignment →
    insert atomic across sessions and replicas, so concurrent appends cannot
    compute the same next `sequence_number` (the prior `FOR UPDATE` tail-row
    lock did not guarantee this under READ COMMITTED). The `UNIQUE`
    `sequence_number` constraint is retained as defense-in-depth, and a bounded
    retry absorbs the rare serialization/unique-conflict so an append never
    surfaces an unhandled database exception as an HTTP 500.

    **Idempotency** is scoped to `(source_principal, event_id)` — the composite
    primary key — so a producer retrying its own `event_id` is a no-op, while
    two different producers using the same `event_id` create distinct events
    (Priority 5). `source_principal` is assigned by the audit service from the
    caller's validated token, never from producer content.
    """

    _TABLE = "audit_events"
    # Fixed 32-bit key ("AUDI") for the chain-wide advisory lock. Distinct from
    # any other advisory lock the platform might use.
    _CHAIN_ADVISORY_LOCK_KEY = 0x41554449
    _MAX_APPEND_ATTEMPTS = 5

    def __init__(self, connection: Connection) -> None:
        self._conn = connection

    def append(
        self,
        event: SubmittedAuditEvent,
        *,
        source_principal: str,
        tenant_id: str | None = None,
    ) -> AuditEvent:
        sanitized = validate_and_sanitize(event)
        import time

        import psycopg

        last_exc: Exception | None = None
        for attempt in range(self._MAX_APPEND_ATTEMPTS):
            try:
                return self._append_once(sanitized, source_principal, tenant_id)
            except (
                psycopg.errors.SerializationFailure,
                psycopg.errors.UniqueViolation,
                psycopg.errors.DeadlockDetected,
            ) as exc:
                # Defense-in-depth: the advisory lock should prevent these, but
                # if one still occurs, roll back and retry with bounded backoff
                # rather than surfacing an unhandled 500.
                self._conn.rollback()
                last_exc = exc
                time.sleep(0.02 * (2**attempt))
        assert last_exc is not None
        raise last_exc

    def _append_once(
        self,
        sanitized: SubmittedAuditEvent,
        source_principal: str,
        tenant_id: str | None,
    ) -> AuditEvent:
        with self._conn.cursor() as cur:
            # Serialize the whole append against the audit chain (released at
            # commit/rollback). All chain reads/writes below happen under it.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (self._CHAIN_ADVISORY_LOCK_KEY,))

            # Idempotency by (source_principal, event_id).
            cur.execute(
                f"SELECT 1 FROM {self._TABLE} WHERE source_principal = %s AND event_id = %s",
                (source_principal, sanitized.event_id),
            )
            if cur.fetchone() is not None:
                self._conn.commit()
                return self._fetch_by_key(source_principal, sanitized.event_id)

            cur.execute(
                f"SELECT sequence_number, event_hash FROM {self._TABLE} "
                "ORDER BY sequence_number DESC LIMIT 1"
            )
            tail = cur.fetchone()
            if tail is None:
                sequence_number = 1
                prev_hash = GENESIS_PREV_HASH
            else:
                sequence_number = int(cast(int, tail[0])) + 1
                prev_hash = str(tail[1])

            persisted = _build_persisted_event(
                sanitized,
                source_principal=source_principal,
                tenant_id=tenant_id,
                sequence_number=sequence_number,
                prev_hash=prev_hash,
            )
            cur.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    event_id, source_principal, tenant_id, sequence_number, timestamp, ingest_time,
                    prev_hash, event_hash, actor, actor_type, module, action,
                    outcome, correlation_id, resource_type, resource_id,
                    classification, source_system, source_component, reason, metadata,
                    schema_version, provenance
                ) VALUES (
                    %(event_id)s, %(source_principal)s, %(tenant_id)s,
                    %(sequence_number)s, %(timestamp)s,
                    %(ingest_time)s, %(prev_hash)s, %(event_hash)s, %(actor)s, %(actor_type)s,
                    %(module)s, %(action)s, %(outcome)s, %(correlation_id)s, %(resource_type)s,
                    %(resource_id)s, %(classification)s, %(source_system)s,
                    %(source_component)s, %(reason)s, %(metadata)s,
                    %(schema_version)s, %(provenance)s
                )
                ON CONFLICT (source_principal, event_id) DO NOTHING
                """,
                self._row_params(persisted),
            )
            self._conn.commit()
            return self._fetch_by_key(source_principal, persisted.event_id)

    def query(self, query: AuditQuery) -> list[AuditEvent]:
        clauses: list[str] = []
        params: dict[str, object] = {}
        # Sprint 6 (FEAT-04-1) filters.
        if query.actor is not None:
            clauses.append("actor = %(actor)s")
            params["actor"] = query.actor
        if query.event_id is not None:
            clauses.append("event_id = %(event_id)s")
            params["event_id"] = query.event_id
        if query.tenant_id is not None:
            clauses.append("tenant_id = %(tenant_id)s")
            params["tenant_id"] = query.tenant_id
        if query.allowed_classifications is not None:
            clauses.append("classification = ANY(%(allowed_classifications)s)")
            params["allowed_classifications"] = [
                value.value for value in query.allowed_classifications
            ]
        if query.correlation_id is not None:
            clauses.append("correlation_id = %(correlation_id)s")
            params["correlation_id"] = query.correlation_id
        if query.start_time is not None:
            clauses.append("timestamp >= %(start_time)s")
            params["start_time"] = query.start_time
        if query.end_time is not None:
            clauses.append("timestamp < %(end_time)s")
            params["end_time"] = query.end_time
        # Sprint 8 (FEAT-04-4) richer filters.
        if query.module is not None:
            clauses.append("module = %(module)s")
            params["module"] = query.module
        if query.action is not None:
            clauses.append("action = %(action)s")
            params["action"] = query.action
        if query.outcome is not None:
            clauses.append("outcome = %(outcome)s")
            params["outcome"] = query.outcome
        if query.source_system is not None:
            clauses.append("source_system = %(source_system)s")
            params["source_system"] = query.source_system
        if query.classification is not None:
            clauses.append("classification = %(classification)s")
            params["classification"] = query.classification.value
        if query.has_provenance is not None:
            clauses.append(
                "provenance IS NOT NULL" if query.has_provenance else "provenance IS NULL"
            )
        # Keyset pagination: only rows strictly after the cursor position.
        if query.cursor is not None:
            clauses.append("sequence_number > %(after_sequence)s")
            params["after_sequence"] = decode_cursor(query.cursor)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params["limit"] = query.limit
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._COLUMNS} FROM {self._TABLE} {where} "
                "ORDER BY sequence_number ASC LIMIT %(limit)s",
                params,
            )
            return [self._row_to_event(row) for row in cur.fetchall()]

    def verify_integrity(self) -> IntegrityReport:
        """Defensively parse each stored row before chain verification. A row
        that no longer parses into a valid `AuditEvent` (e.g. a tampered
        `outcome`/`timestamp` that violates the schema) is reported as an
        integrity failure at its raw `sequence_number` — it never surfaces as
        an HTTP 500 (Sprint 6 security-review fix, Priority 4). `sequence_number`
        is read as a raw integer, which remains valid even when other columns
        were tampered."""
        events: list[AuditEvent] = []
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT {self._COLUMNS} FROM {self._TABLE} ORDER BY sequence_number ASC")
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
                            f"stored record at sequence {raw_seq} failed to parse "
                            f"(schema-violating tamper): {exc}"
                        ),
                    )
        return verify_chain(events)

    @staticmethod
    def _raw_sequence(row: tuple[object, ...]) -> int | None:
        try:
            return int(cast(int, row[2]))  # sequence_number column (see _COLUMNS)
        except Exception:  # pragma: no cover - defensive
            return None

    # --- row mapping -------------------------------------------------------

    # schema_version and provenance are appended at the end so every existing
    # column index (used positionally in _row_to_event and _raw_sequence) is
    # unchanged — additive, backward-compatible column layout (FEAT-04-2).
    _COLUMNS = (
        "event_id, source_principal, sequence_number, timestamp, ingest_time, prev_hash, "
        "event_hash, actor, actor_type, module, action, outcome, correlation_id, "
        "resource_type, resource_id, classification, source_system, source_component, "
        "reason, metadata, schema_version, provenance, tenant_id"
    )

    def _fetch_by_key(self, source_principal: str, event_id: str) -> AuditEvent:
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._COLUMNS} FROM {self._TABLE} "
                "WHERE source_principal = %s AND event_id = %s",
                (source_principal, event_id),
            )
            row = cur.fetchone()
        if row is None:  # pragma: no cover - defensive
            raise RuntimeError(f"audit event {event_id!r} not found immediately after insert")
        return self._row_to_event(row)

    @staticmethod
    def _row_params(event: AuditEvent) -> dict[str, object]:
        import json

        provenance = (
            None
            if event.provenance is None
            else json.dumps(event.provenance.model_dump(mode="json"))
        )
        return {
            "event_id": event.event_id,
            "source_principal": event.source_principal,
            "tenant_id": event.tenant_id or "legacy-unscoped",
            "sequence_number": event.sequence_number,
            "timestamp": event.timestamp,
            "ingest_time": event.ingest_time,
            "prev_hash": event.prev_hash,
            "event_hash": event.event_hash,
            "actor": event.actor,
            "actor_type": event.actor_type,
            "module": event.module,
            "action": event.action,
            "outcome": event.outcome,
            "correlation_id": event.correlation_id,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "classification": event.classification.value,
            "source_system": event.source_system,
            "source_component": event.source_component,
            "reason": event.reason,
            "metadata": json.dumps(event.metadata),
            "schema_version": event.schema_version,
            "provenance": provenance,
        }

    @staticmethod
    def _row_to_event(row: tuple[object, ...]) -> AuditEvent:
        import json

        from emg_audit_client import ProvenanceRecord
        from emg_common_types import Classification

        raw_metadata = row[19]
        metadata = raw_metadata if isinstance(raw_metadata, dict) else json.loads(str(raw_metadata))
        # schema_version / provenance columns are appended (FEAT-04-2); a
        # pre-migration row (Sprint 6) has schema_version defaulted to 1 by the
        # DB and provenance NULL, so it reconstructs as a version-1 event whose
        # stored hash still verifies.
        raw_schema_version = row[20] if len(row) > 20 else None
        schema_version = (
            EVENT_SCHEMA_VERSION_V1
            if raw_schema_version is None
            else int(cast(int, raw_schema_version))
        )
        raw_provenance = row[21] if len(row) > 21 else None
        tenant_id = None if len(row) <= 22 or row[22] is None else str(row[22])
        if raw_provenance is None:
            provenance = None
        elif isinstance(raw_provenance, dict):
            provenance = ProvenanceRecord.model_validate(raw_provenance)
        else:
            provenance = ProvenanceRecord.model_validate_json(str(raw_provenance))
        return AuditEvent(
            event_id=str(row[0]),
            source_principal=str(row[1]),
            tenant_id=tenant_id,
            sequence_number=int(cast(int, row[2])),
            schema_version=schema_version,
            timestamp=cast(datetime, row[3]),
            ingest_time=cast(datetime, row[4]),
            prev_hash=str(row[5]),
            event_hash=str(row[6]),
            actor=str(row[7]),
            actor_type=row[8],  # type: ignore[arg-type]
            module=str(row[9]),
            action=str(row[10]),
            outcome=row[11],  # type: ignore[arg-type]
            correlation_id=None if row[12] is None else str(row[12]),
            resource_type=None if row[13] is None else str(row[13]),
            resource_id=None if row[14] is None else str(row[14]),
            classification=Classification(str(row[15])),
            source_system=str(row[16]),
            source_component=None if row[17] is None else str(row[17]),
            reason=str(row[18]),
            metadata=metadata,
            provenance=provenance,
        )
