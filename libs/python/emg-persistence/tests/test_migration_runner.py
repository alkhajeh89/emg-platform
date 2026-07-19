"""MigrationRunner: apply, idempotency, checksum/dirty/failed detection,
forward-only ordering, status (Sprint 2)."""

from __future__ import annotations

import pytest
from _migr_helpers import FakeMigrationExecutor, make_applied, make_migration
from emg_persistence.migrations import (
    ChecksumMismatchError,
    DirtyMigrationError,
    FailedMigrationError,
    MigrationDiscoveryError,
    MigrationKind,
    MigrationRunner,
)


def test_run_applies_pending_in_order() -> None:
    ex = FakeMigrationExecutor()
    m1, m2 = make_migration(1), make_migration(2)
    applied = MigrationRunner(ex).run([m2, m1])  # unordered input
    assert [a.version for a in applied] == [1, 2]
    assert ex.ensure_history_calls == 1


def test_repeated_run_is_idempotent() -> None:
    ex = FakeMigrationExecutor()
    migs = [make_migration(1), make_migration(2)]
    runner = MigrationRunner(ex)
    assert len(runner.run(migs)) == 2
    assert runner.run(migs) == ()  # nothing pending the second time


def test_checksum_mismatch_detected() -> None:
    m1 = make_migration(1, statements="SELECT 1;")
    # applied recorded with a DIFFERENT checksum than the on-disk migration
    ex = FakeMigrationExecutor(applied=[make_applied(1, "b" * 64)])
    with pytest.raises(ChecksumMismatchError):
        MigrationRunner(ex).run([m1])


def test_applied_missing_on_disk_detected() -> None:
    ex = FakeMigrationExecutor(applied=[make_applied(1, "a" * 64)])
    with pytest.raises(ChecksumMismatchError):
        MigrationRunner(ex).run([])  # version 1 applied but not present on disk


def test_dirty_migration_halts() -> None:
    m1 = make_migration(1)
    ex = FakeMigrationExecutor(applied=[make_applied(1, m1.checksum, dirty=True)])
    with pytest.raises(DirtyMigrationError):
        MigrationRunner(ex).run([m1])


def test_failed_migration_halts() -> None:
    m1 = make_migration(1)
    ex = FakeMigrationExecutor(applied=[make_applied(1, m1.checksum, success=False)])
    with pytest.raises(FailedMigrationError):
        MigrationRunner(ex).run([m1])


def test_apply_failure_records_dirty_then_halts_next_run() -> None:
    # Models a transactional backend: the failed migration rolls back and a dirty
    # marker is recorded; the next run detects the dirty state and halts.
    m1, m2 = make_migration(1), make_migration(2)
    ex = FakeMigrationExecutor(fail_versions={2})
    runner = MigrationRunner(ex)
    with pytest.raises(FailedMigrationError):
        runner.run([m1, m2])
    assert [a.version for a in ex.fetch_applied()] == [1, 2]  # v1 ok, v2 dirty
    with pytest.raises(DirtyMigrationError):
        runner.run([m1, m2])


def test_forward_only_violation() -> None:
    # v2 already applied; a new v1 appears pending -> forward-only violation.
    m1, m2 = make_migration(1), make_migration(2)
    ex = FakeMigrationExecutor(applied=[make_applied(2, m2.checksum)])
    with pytest.raises(MigrationDiscoveryError):
        MigrationRunner(ex).run([m1, m2])


def test_mixed_kinds_rejected() -> None:
    ex = FakeMigrationExecutor()
    pg = make_migration(1, kind=MigrationKind.POSTGRES)
    neo = make_migration(2, kind=MigrationKind.NEO4J)
    with pytest.raises(MigrationDiscoveryError):
        MigrationRunner(ex).run([pg, neo])


def test_duplicate_version_in_input_rejected() -> None:
    ex = FakeMigrationExecutor()
    with pytest.raises(MigrationDiscoveryError):
        MigrationRunner(ex).run([make_migration(1, "a"), make_migration(1, "b")])


def test_status_reporting() -> None:
    m1, m2 = make_migration(1), make_migration(2)
    ex = FakeMigrationExecutor(applied=[make_applied(1, m1.checksum)])
    status = MigrationRunner(ex).status([m1, m2])
    assert [a.version for a in status.applied] == [1]
    assert [m.version for m in status.pending] == [2]
    assert status.is_up_to_date is False
    assert status.is_dirty is False


def test_status_up_to_date() -> None:
    m1 = make_migration(1)
    ex = FakeMigrationExecutor(applied=[make_applied(1, m1.checksum)])
    status = MigrationRunner(ex).status([m1])
    assert status.is_up_to_date is True
