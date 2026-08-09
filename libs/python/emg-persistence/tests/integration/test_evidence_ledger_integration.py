"""Live PostgreSQL coverage for the accepted P-02 evidence-ledger contract."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import pytest
from _persistence_integration_helpers import truncate_persistence_tables
from emg_memory_graph import EvidenceRef, EvidenceSource, Metadata
from emg_persistence import EvidenceLedgerIntegrityError, PersistenceSettings
from emg_persistence.evidence import (
    GENESIS_PREV_HASH,
    EvidenceIntegrityFailureKind,
    compute_evidence_entry_hash,
)
from emg_persistence.migrate import run_migrations
from emg_persistence.postgres import PostgresMigrationExecutor, connect
from emg_persistence.postgres.evidence_repository import (
    _ADVISORY_LOCK_NAMESPACE,
    PostgresEvidenceLedgerRepository,
)
from emg_platform_core import TenantId
from psycopg import Connection
from psycopg.errors import CheckViolation, NotNullViolation, RaiseException

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)

TENANT_A = TenantId.of("evidence-tenant-a")
TENANT_B = TenantId.of("evidence-tenant-b")
CAPTURED_AT = datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc)


def _evidence(locator: str, *, description: str | None = None) -> EvidenceRef:
    return EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator=locator,
        source_principal="svc-evidence",
        captured_at=CAPTURED_AT,
        description=description,
        event_id=f"event-{locator}",
        correlation_id=f"correlation-{locator}",
        metadata=Metadata.from_mapping({"classification": "internal"}),
    )


def _insert_raw_entry(
    connection: Connection[Any],
    *,
    tenant_id: str,
    seq: int,
    prev_hash: str | None,
    entry_hash: str,
) -> None:
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO evidence_ledger (tenant_id, seq, evidence_id, prev_hash, "
            "entry_hash, source, locator, source_principal, captured_at, payload) "
            "VALUES (%s, %s, %s, %s, %s, 'pdf', %s, 'svc-evidence', %s, '{}'::jsonb)",
            (
                tenant_id,
                seq,
                f"evidence-{tenant_id}-{seq}",
                prev_hash,
                entry_hash,
                f"{tenant_id}-{seq}.pdf",
                CAPTURED_AT,
            ),
        )


def _tamper_out_of_band(
    connection: Connection[Any], statement: str, parameters: tuple[object, ...]
) -> None:
    """Model a privileged actor bypassing the trigger, then restore it."""
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("ALTER TABLE evidence_ledger DISABLE TRIGGER evidence_ledger_append_only")
        try:
            cursor.execute(statement, parameters)
        finally:
            cursor.execute("ALTER TABLE evidence_ledger ENABLE TRIGGER evidence_ledger_append_only")


@pytest.fixture
def settings() -> PersistenceSettings:  # pragma: no cover - live DB only
    return PersistenceSettings(postgres_dsn=_PG_DSN)


@pytest.fixture(autouse=True)
def clean_database(settings: PersistenceSettings) -> Iterator[None]:  # pragma: no cover
    connection = connect(settings)
    run_migrations(PostgresMigrationExecutor(connection))
    truncate_persistence_tables(connection)
    connection.commit()
    connection.close()
    try:
        yield
    finally:
        connection = connect(settings)
        truncate_persistence_tables(connection)
        connection.commit()
        connection.close()


@pytest.fixture
def connection(settings: PersistenceSettings) -> Iterator[Connection[Any]]:
    # pragma: no cover - live DB only
    value = connect(settings)
    try:
        yield value
    finally:
        value.close()


@requires_postgres
def test_append_duplicate_capture_read_and_tenant_isolation(
    connection: Connection[Any],
) -> None:  # pragma: no cover - live DB only
    repository = PostgresEvidenceLedgerRepository(connection)
    evidence = _evidence("duplicate.pdf")

    first = repository.append(TENANT_A, evidence)
    second = repository.append(TENANT_A, evidence)
    tenant_b_first = repository.append(TENANT_B, _evidence("tenant-b.pdf"))

    assert first.seq == 1
    assert first.prev_hash == GENESIS_PREV_HASH
    assert second.seq == 2
    assert second.prev_hash == first.entry_hash
    assert second.entry_hash != first.entry_hash
    assert tenant_b_first.seq == 1
    assert tenant_b_first.prev_hash == GENESIS_PREV_HASH
    assert repository.get(TENANT_A, 1) == first
    assert repository.get(TENANT_B, 1) == tenant_b_first
    assert repository.get(TENANT_B, 2) is None
    assert repository.list_range(TENANT_A, start_seq=1, end_seq=100) == (first, second)
    assert repository.verify_range(TENANT_A, start_seq=1, end_seq=100).valid is True
    assert repository.verify_range(TENANT_A, start_seq=2, end_seq=2).valid is True
    assert repository.verify_range(TENANT_B, start_seq=1, end_seq=100).valid is True


@requires_postgres
def test_database_accepts_canonical_genesis_and_chained_repository_appends(
    connection: Connection[Any],
) -> None:
    repository = PostgresEvidenceLedgerRepository(connection)

    first = repository.append(TENANT_A, _evidence("canonical-genesis.pdf"))
    second = repository.append(TENANT_A, _evidence("canonical-chain.pdf"))

    assert first.seq == 1
    assert first.prev_hash == GENESIS_PREV_HASH
    assert second.seq == 2
    assert second.prev_hash == first.entry_hash
    assert repository.verify_range(TENANT_A, start_seq=1, end_seq=2).valid is True


@requires_postgres
@pytest.mark.parametrize("invalid_seq", [0, -1])
def test_database_rejects_non_positive_sequence(
    connection: Connection[Any], invalid_seq: int
) -> None:
    with pytest.raises(CheckViolation, match="ck_evidence_ledger_seq_positive"):
        _insert_raw_entry(
            connection,
            tenant_id=f"invalid-seq-{invalid_seq}",
            seq=invalid_seq,
            prev_hash=GENESIS_PREV_HASH,
            entry_hash="a" * 64,
        )


@requires_postgres
@pytest.mark.parametrize(
    "invalid_prev_hash",
    ["", "a" * 63, "A" * 64, "g" * 64, "a" * 64 + "\n"],
)
def test_database_rejects_malformed_prev_hash(
    connection: Connection[Any], invalid_prev_hash: str
) -> None:
    with pytest.raises(CheckViolation, match="ck_evidence_ledger_prev_hash_format"):
        _insert_raw_entry(
            connection,
            tenant_id=f"invalid-prev-{len(invalid_prev_hash)}-{invalid_prev_hash[:1]}",
            seq=2,
            prev_hash=invalid_prev_hash,
            entry_hash="a" * 64,
        )


@requires_postgres
def test_database_rejects_null_non_genesis_prev_hash(connection: Connection[Any]) -> None:
    with pytest.raises(NotNullViolation, match="prev_hash"):
        _insert_raw_entry(
            connection,
            tenant_id="null-prev",
            seq=2,
            prev_hash=None,
            entry_hash="a" * 64,
        )


@requires_postgres
def test_database_rejects_noncanonical_genesis_prev_hash(connection: Connection[Any]) -> None:
    with pytest.raises(CheckViolation, match="ck_evidence_ledger_genesis_prev_hash"):
        _insert_raw_entry(
            connection,
            tenant_id="invalid-genesis",
            seq=1,
            prev_hash="a" * 64,
            entry_hash="b" * 64,
        )


@requires_postgres
@pytest.mark.parametrize(
    "invalid_entry_hash",
    ["", "a" * 63, "A" * 64, "g" * 64, "a" * 64 + "\n"],
)
def test_database_rejects_malformed_entry_hash(
    connection: Connection[Any], invalid_entry_hash: str
) -> None:
    with pytest.raises(CheckViolation, match="ck_evidence_ledger_entry_hash_format"):
        _insert_raw_entry(
            connection,
            tenant_id=f"invalid-entry-{len(invalid_entry_hash)}-{invalid_entry_hash[:1]}",
            seq=1,
            prev_hash=GENESIS_PREV_HASH,
            entry_hash=invalid_entry_hash,
        )


@requires_postgres
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE evidence_ledger SET locator = 'forbidden' " "WHERE tenant_id = %s AND seq = 1",
        "DELETE FROM evidence_ledger WHERE tenant_id = %s AND seq = 1",
    ],
)
def test_database_rejects_update_and_delete(connection: Connection[Any], statement: str) -> None:
    repository = PostgresEvidenceLedgerRepository(connection)
    repository.append(TENANT_A, _evidence("append-only.pdf"))

    with (
        pytest.raises(RaiseException, match="evidence_ledger is append-only"),
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement, (TENANT_A.value,))


@requires_postgres
def test_rolled_back_append_consumes_no_sequence(
    connection: Connection[Any],
) -> None:  # pragma: no cover - live DB only
    repository = PostgresEvidenceLedgerRepository(connection)

    with pytest.raises(RuntimeError, match="rollback"), connection.transaction():
        pending = repository.append(TENANT_A, _evidence("rolled-back.pdf"))
        assert pending.seq == 1
        raise RuntimeError("rollback")

    committed = repository.append(TENANT_A, _evidence("committed.pdf"))

    assert committed.seq == 1
    assert committed.prev_hash == GENESIS_PREV_HASH


@requires_postgres
def test_concurrent_same_tenant_appends_are_gapless_and_single_linked(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB only
    workers = 12
    barrier = threading.Barrier(workers)

    def append(index: int) -> tuple[int, str, str]:
        worker_connection = connect(settings)
        try:
            barrier.wait()
            entry = PostgresEvidenceLedgerRepository(worker_connection).append(
                TENANT_A,
                _evidence(f"concurrent-{index}.pdf"),
            )
            return entry.seq, entry.prev_hash, entry.entry_hash
        finally:
            worker_connection.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = tuple(executor.map(append, range(workers)))

    assert sorted(seq for seq, _prev_hash, _entry_hash in results) == list(range(1, workers + 1))
    assert len({entry_hash for _seq, _prev_hash, entry_hash in results}) == workers
    assert len({prev_hash for _seq, prev_hash, _entry_hash in results}) == workers

    connection = connect(settings)
    try:
        repository = PostgresEvidenceLedgerRepository(connection)
        entries = repository.list_range(TENANT_A, start_seq=1, end_seq=workers)
        assert [entry.seq for entry in entries] == list(range(1, workers + 1))
        assert repository.verify_range(TENANT_A, start_seq=1, end_seq=workers).valid is True
    finally:
        connection.close()


@requires_postgres
def test_different_tenant_append_does_not_wait_on_another_tenant_lock(
    settings: PersistenceSettings,
) -> None:  # pragma: no cover - live DB only
    blocker = connect(settings)
    worker = connect(settings)
    try:
        with blocker.transaction(), blocker.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, %s))",
                (TENANT_A.value, _ADVISORY_LOCK_NAMESPACE),
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    PostgresEvidenceLedgerRepository(worker).append,
                    TENANT_B,
                    _evidence("other-tenant.pdf"),
                )
                assert future.result(timeout=2).seq == 1
    finally:
        blocker.close()
        worker.close()


@requires_postgres
def test_corrupt_entry_fails_closed_but_historical_break_does_not_block_append(
    connection: Connection[Any],
) -> None:  # pragma: no cover - live DB only
    repository = PostgresEvidenceLedgerRepository(connection)
    for index in range(1, 4):
        repository.append(TENANT_A, _evidence(f"corrupt-{index}.pdf", description="canary"))

    _tamper_out_of_band(
        connection,
        "UPDATE evidence_ledger SET locator = 'tampered' WHERE tenant_id = %s AND seq = 2",
        (TENANT_A.value,),
    )

    with pytest.raises(EvidenceLedgerIntegrityError, match="evidence-tenant-a.*seq 2") as caught:
        repository.get(TENANT_A, 2)
    with pytest.raises(EvidenceLedgerIntegrityError):
        repository.list_range(TENANT_A, start_seq=1, end_seq=3)
    assert "canary" not in str(caught.value)

    report = repository.verify_range(TENANT_A, start_seq=1, end_seq=3)
    assert report.valid is False
    assert report.first_failing_seq == 2
    assert report.failure_kind is EvidenceIntegrityFailureKind.ENTRY_HASH

    appended = repository.append(TENANT_A, _evidence("after-break.pdf"))
    assert appended.seq == 4
    assert repository.verify_range(TENANT_A, start_seq=1, end_seq=4).first_failing_seq == 2


@requires_postgres
def test_range_verification_detects_validly_rehashed_broken_link(
    connection: Connection[Any],
) -> None:  # pragma: no cover - live DB only
    repository = PostgresEvidenceLedgerRepository(connection)
    first = repository.append(TENANT_A, _evidence("link-1.pdf"))
    second = repository.append(TENANT_A, _evidence("link-2.pdf"))
    repository.append(TENANT_A, _evidence("link-3.pdf"))
    wrong_prev_hash = "f" * 64
    rehashed = compute_evidence_entry_hash(
        tenant=TENANT_A,
        seq=second.seq,
        prev_hash=wrong_prev_hash,
        evidence=second.evidence,
    )

    _tamper_out_of_band(
        connection,
        "UPDATE evidence_ledger SET prev_hash = %s, entry_hash = %s "
        "WHERE tenant_id = %s AND seq = %s",
        (wrong_prev_hash, rehashed, TENANT_A.value, second.seq),
    )

    assert repository.get(TENANT_A, 2) is not None
    report = repository.verify_range(TENANT_A, start_seq=1, end_seq=3)

    assert report.valid is False
    assert report.first_failing_seq == 2
    assert report.failure_kind is EvidenceIntegrityFailureKind.PREV_HASH
    assert first.entry_hash != wrong_prev_hash


@requires_postgres
def test_range_verification_detects_sequence_gap(
    connection: Connection[Any],
) -> None:  # pragma: no cover - live DB only
    repository = PostgresEvidenceLedgerRepository(connection)
    for index in range(1, 4):
        repository.append(TENANT_A, _evidence(f"gap-{index}.pdf"))

    _tamper_out_of_band(
        connection,
        "DELETE FROM evidence_ledger WHERE tenant_id = %s AND seq = 2",
        (TENANT_A.value,),
    )

    report = repository.verify_range(TENANT_A, start_seq=1, end_seq=3)

    assert report.valid is False
    assert report.first_failing_seq == 3
    assert report.failure_kind is EvidenceIntegrityFailureKind.SEQUENCE
