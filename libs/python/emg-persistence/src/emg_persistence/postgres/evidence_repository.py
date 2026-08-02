"""PostgreSQL implementation of the internal evidence-ledger contract.

Append serialization uses a transaction-scoped PostgreSQL advisory lock whose
64-bit key is derived from the explicit tenant identifier.  The lock is held
from tail read through insert, so same-tenant allocation is gapless under READ
COMMITTED while different tenants use independent lock keys.  The primary key
remains defense-in-depth and is not the sequence allocator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from emg_memory_graph import EvidenceRef
from emg_platform_core import TenantId
from psycopg import Error as PsycopgError
from psycopg.errors import DeadlockDetected, SerializationFailure, UniqueViolation

from ..errors import (
    EvidenceLedgerIntegrityError,
    PersistenceConflictError,
    PersistenceError,
)
from ..evidence import (
    GENESIS_PREV_HASH,
    EvidenceEntry,
    EvidenceIntegrityFailureKind,
    EvidenceVerificationReport,
    as_utc_datetime,
    build_evidence_entry,
    canonical_evidence_payload,
    inspect_persisted_entry,
    require_persisted_entry,
)

if TYPE_CHECKING:
    from psycopg import Connection

_ADVISORY_LOCK_NAMESPACE = 0x454D475F45564C

_LOCK_TENANT = """
SELECT pg_advisory_xact_lock(
    hashtextextended(%(tenant_id)s, %(lock_namespace)s)
)
"""

_SELECT_TAIL = """
SELECT seq, entry_hash
FROM evidence_ledger
WHERE tenant_id = %(tenant_id)s
ORDER BY seq DESC
LIMIT 1
"""

_INSERT_ENTRY = """
INSERT INTO evidence_ledger (
    tenant_id,
    seq,
    evidence_id,
    prev_hash,
    entry_hash,
    source,
    locator,
    source_principal,
    captured_at,
    payload
)
VALUES (
    %(tenant_id)s,
    %(seq)s,
    %(evidence_id)s,
    %(prev_hash)s,
    %(entry_hash)s,
    %(source)s,
    %(locator)s,
    %(source_principal)s,
    %(captured_at)s,
    %(payload)s
)
"""

_SELECT_ENTRY = """
SELECT
    tenant_id,
    seq,
    evidence_id,
    prev_hash,
    entry_hash,
    source,
    locator,
    source_principal,
    captured_at,
    payload
FROM evidence_ledger
WHERE tenant_id = %(tenant_id)s
  AND seq = %(seq)s
"""

_SELECT_RANGE = """
SELECT
    tenant_id,
    seq,
    evidence_id,
    prev_hash,
    entry_hash,
    source,
    locator,
    source_principal,
    captured_at,
    payload
FROM evidence_ledger
WHERE tenant_id = %(tenant_id)s
  AND seq >= %(start_seq)s
  AND seq <= %(end_seq)s
ORDER BY seq ASC
"""


class PostgresEvidenceLedgerRepository:
    """Tenant-scoped PostgreSQL evidence chain with no mutation or repair API."""

    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection

    def append(self, tenant: TenantId, evidence: EvidenceRef) -> EvidenceEntry:
        """Append one entry in an atomic, same-tenant-serialized transaction."""

        from psycopg.types.json import Jsonb

        try:
            with self._connection.transaction(), self._connection.cursor() as cursor:
                cursor.execute(
                    _LOCK_TENANT,
                    {
                        "tenant_id": tenant.value,
                        "lock_namespace": _ADVISORY_LOCK_NAMESPACE,
                    },
                )
                cursor.execute(_SELECT_TAIL, {"tenant_id": tenant.value})
                tail = cursor.fetchone()
                if tail is None:
                    seq = 1
                    prev_hash = GENESIS_PREV_HASH
                else:
                    tail_seq = int(tail[0])
                    tail_hash = tail[1]
                    if tail_seq < 1 or not _is_hash(tail_hash):
                        raise EvidenceLedgerIntegrityError(
                            "evidence ledger integrity failure for tenant "
                            f"{tenant.value!r} at seq {tail_seq}"
                        )
                    seq = tail_seq + 1
                    prev_hash = str(tail_hash)

                entry = build_evidence_entry(
                    tenant=tenant,
                    seq=seq,
                    prev_hash=prev_hash,
                    evidence=evidence,
                )
                cursor.execute(
                    _INSERT_ENTRY,
                    {
                        "tenant_id": tenant.value,
                        "seq": entry.seq,
                        "evidence_id": str(entry.evidence.evidence_id),
                        "prev_hash": entry.prev_hash,
                        "entry_hash": entry.entry_hash,
                        "source": entry.evidence.source.value,
                        "locator": str(entry.evidence.locator),
                        "source_principal": str(entry.evidence.source_principal),
                        "captured_at": as_utc_datetime(entry.evidence.captured_at),
                        "payload": Jsonb(canonical_evidence_payload(entry.evidence)),
                    },
                )
                return entry
        except EvidenceLedgerIntegrityError:
            raise
        except (DeadlockDetected, SerializationFailure, UniqueViolation) as exc:
            raise PersistenceConflictError(
                f"evidence ledger append conflict for tenant {tenant.value!r}"
            ) from exc
        except PersistenceError:
            raise
        except PsycopgError as exc:
            raise PersistenceError(
                f"failed to append evidence for tenant {tenant.value!r}"
            ) from exc

    def get(self, tenant: TenantId, seq: int) -> EvidenceEntry | None:
        """Return one verified entry without traversing the tenant's history."""

        _validate_seq(seq)
        try:
            with self._connection.transaction(), self._connection.cursor() as cursor:
                cursor.execute(
                    _SELECT_ENTRY,
                    {"tenant_id": tenant.value, "seq": seq},
                )
                row = cursor.fetchone()
        except PsycopgError as exc:
            raise PersistenceError(
                f"failed to read evidence for tenant {tenant.value!r} at seq {seq}"
            ) from exc
        return None if row is None else _require_row(tenant, row)

    def list_range(
        self, tenant: TenantId, *, start_seq: int, end_seq: int
    ) -> tuple[EvidenceEntry, ...]:
        """Return only verified entries from the inclusive requested range."""

        _validate_range(start_seq, end_seq)
        rows = self._range_rows(tenant, start_seq=start_seq, end_seq=end_seq)
        return tuple(_require_row(tenant, row) for row in rows)

    def verify_range(
        self, tenant: TenantId, *, start_seq: int, end_seq: int
    ) -> EvidenceVerificationReport:
        """Explicitly verify entry hashes and contiguous links in one range."""

        _validate_range(start_seq, end_seq)
        query_start = max(1, start_seq - 1)
        rows = self._range_rows(tenant, start_seq=query_start, end_seq=end_seq)

        predecessor: tuple[Any, ...] | None = None
        relevant_rows = rows
        if start_seq > 1 and rows and int(rows[0][1]) == start_seq - 1:
            predecessor = rows[0]
            relevant_rows = rows[1:]

        if not relevant_rows:
            return _valid_report(tenant, start_seq, end_seq, verified_entries=0)

        expected_seq = start_seq
        verified_entries = 0
        previous_hash: object = None if predecessor is None else predecessor[4]
        for row in relevant_rows:
            row_seq = int(row[1])
            if row_seq != expected_seq:
                return _invalid_report(
                    tenant,
                    start_seq,
                    end_seq,
                    verified_entries,
                    row_seq,
                    EvidenceIntegrityFailureKind.SEQUENCE,
                )

            entry, failure = _inspect_row(tenant, row)
            if entry is None:
                assert failure is not None
                return _invalid_report(
                    tenant,
                    start_seq,
                    end_seq,
                    verified_entries,
                    row_seq,
                    failure,
                )

            if row_seq == 1:
                expected_prev_hash: object = GENESIS_PREV_HASH
            else:
                if not _is_hash(previous_hash):
                    return _invalid_report(
                        tenant,
                        start_seq,
                        end_seq,
                        verified_entries,
                        row_seq,
                        EvidenceIntegrityFailureKind.SEQUENCE,
                    )
                expected_prev_hash = previous_hash
            if entry.prev_hash != expected_prev_hash:
                return _invalid_report(
                    tenant,
                    start_seq,
                    end_seq,
                    verified_entries,
                    row_seq,
                    EvidenceIntegrityFailureKind.PREV_HASH,
                )

            previous_hash = entry.entry_hash
            expected_seq += 1
            verified_entries += 1

        return _valid_report(
            tenant,
            start_seq,
            end_seq,
            verified_entries=verified_entries,
        )

    def _range_rows(
        self, tenant: TenantId, *, start_seq: int, end_seq: int
    ) -> tuple[tuple[Any, ...], ...]:
        try:
            with self._connection.transaction(), self._connection.cursor() as cursor:
                cursor.execute(
                    _SELECT_RANGE,
                    {
                        "tenant_id": tenant.value,
                        "start_seq": start_seq,
                        "end_seq": end_seq,
                    },
                )
                return tuple(cursor.fetchall())
        except PsycopgError as exc:
            raise PersistenceError(
                f"failed to read evidence range for tenant {tenant.value!r}"
            ) from exc


def _inspect_row(
    tenant: TenantId, row: tuple[Any, ...]
) -> tuple[EvidenceEntry | None, EvidenceIntegrityFailureKind | None]:
    return inspect_persisted_entry(
        tenant=tenant,
        seq=int(row[1]),
        evidence_id=row[2],
        prev_hash=row[3],
        entry_hash=row[4],
        source=row[5],
        locator=row[6],
        source_principal=row[7],
        captured_at=row[8],
        payload=row[9],
    )


def _require_row(tenant: TenantId, row: tuple[Any, ...]) -> EvidenceEntry:
    return require_persisted_entry(
        tenant=tenant,
        seq=int(row[1]),
        evidence_id=row[2],
        prev_hash=row[3],
        entry_hash=row[4],
        source=row[5],
        locator=row[6],
        source_principal=row[7],
        captured_at=row[8],
        payload=row[9],
    )


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_seq(seq: int) -> None:
    if seq < 1:
        raise ValueError(f"seq must be at least 1: {seq!r}")


def _validate_range(start_seq: int, end_seq: int) -> None:
    _validate_seq(start_seq)
    _validate_seq(end_seq)
    if end_seq < start_seq:
        raise ValueError(
            f"end_seq must be greater than or equal to start_seq: {end_seq!r} < {start_seq!r}"
        )


def _valid_report(
    tenant: TenantId,
    start_seq: int,
    end_seq: int,
    *,
    verified_entries: int,
) -> EvidenceVerificationReport:
    return EvidenceVerificationReport(
        tenant_id=tenant,
        start_seq=start_seq,
        end_seq=end_seq,
        valid=True,
        verified_entries=verified_entries,
    )


def _invalid_report(
    tenant: TenantId,
    start_seq: int,
    end_seq: int,
    verified_entries: int,
    first_failing_seq: int,
    failure_kind: EvidenceIntegrityFailureKind,
) -> EvidenceVerificationReport:
    return EvidenceVerificationReport(
        tenant_id=tenant,
        start_seq=start_seq,
        end_seq=end_seq,
        valid=False,
        verified_entries=verified_entries,
        first_failing_seq=first_failing_seq,
        failure_kind=failure_kind,
    )
