"""migrate.py orchestration + packaged baseline migrations (Sprint 2)."""

from __future__ import annotations

from _migr_helpers import FakeMigrationExecutor
from emg_persistence.migrate import default_migrations_dir, migration_status, run_migrations
from emg_persistence.migrations import MigrationKind


def test_default_dirs_contain_baseline() -> None:
    pg_dir = default_migrations_dir(MigrationKind.POSTGRES)
    neo_dir = default_migrations_dir(MigrationKind.NEO4J)
    assert (pg_dir / "V001__baseline.sql").is_file()
    assert (pg_dir / "V002__projection_checkpoints.sql").is_file()
    assert (pg_dir / "V003__mutation_idempotency.sql").is_file()
    assert (pg_dir / "V004__mutation_ledger.sql").is_file()
    assert (neo_dir / "M001__constraints.cypher").is_file()


def test_run_migrations_applies_packaged_postgres_baseline() -> None:
    ex = FakeMigrationExecutor(MigrationKind.POSTGRES)
    applied = run_migrations(ex)  # uses the packaged default dir
    assert [a.version for a in applied] == [1, 2, 3, 4]
    assert applied[0].name == "baseline"
    assert applied[1].name == "projection_checkpoints"
    assert applied[2].name == "mutation_idempotency"
    assert applied[3].name == "mutation_ledger"
    # idempotent second run
    assert run_migrations(ex) == ()


def test_run_migrations_applies_packaged_neo4j_baseline() -> None:
    ex = FakeMigrationExecutor(MigrationKind.NEO4J)
    applied = run_migrations(ex)
    assert [a.version for a in applied] == [1]
    assert applied[0].kind is MigrationKind.NEO4J


def test_migration_status_reports_pending_baseline() -> None:
    ex = FakeMigrationExecutor(MigrationKind.POSTGRES)
    status = migration_status(ex)
    assert [m.version for m in status.pending] == [1, 2, 3, 4]
    assert status.is_up_to_date is False


def test_run_migrations_explicit_dir(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "V001__x.sql").write_text("SELECT 1;", encoding="utf-8")
    ex = FakeMigrationExecutor(MigrationKind.POSTGRES)
    applied = run_migrations(ex, tmp_path)
    assert [a.version for a in applied] == [1]
