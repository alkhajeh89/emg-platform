from __future__ import annotations

from emg_persistence.migrate import default_migrations_dir
from emg_persistence.migrations import MigrationKind


def _migration() -> str:
    path = default_migrations_dir(MigrationKind.POSTGRES) / "V004__mutation_ledger.sql"
    return path.read_text(encoding="utf-8")


def test_v004_preserves_v003_rows_as_non_replayable_legacy_records() -> None:
    sql = _migration()
    assert "state text NOT NULL DEFAULT 'legacy_succeeded'" in sql
    assert "state = 'legacy_succeeded'" in sql
    assert "command_fingerprint IS NULL" in sql
    assert "mutation_id IS NULL" in sql


def test_v004_defines_atomic_claim_and_append_only_ledger_constraints() -> None:
    sql = _migration()
    v003 = (
        default_migrations_dir(MigrationKind.POSTGRES) / "V003__mutation_idempotency.sql"
    ).read_text(encoding="utf-8")
    assert "state = 'pending'" in sql
    assert "state = 'succeeded'" in sql
    assert "PRIMARY KEY (tenant_id, principal_id, idempotency_key)" in v003
    assert "mutation_ledger_append_only" in sql
    assert "mutation_ledger_resource_append_only" in sql
    assert "mutation_ledger_json_integrity" in sql


def test_v004_dispatch_is_work_set_based_and_lsn_aware() -> None:
    sql = _migration()
    assert "CREATE TABLE mutation_dispatch" in sql
    assert "source_commit_lsn pg_lsn" in sql
    assert "source_timeline" in sql
    assert "source_tx_index" in sql
    assert "ix_mutation_dispatch_work" in sql
    assert "UUIDv7" not in sql


def test_v004_separates_graph_and_ledger_timestamps() -> None:
    sql = _migration()
    assert "ledger_completed_at" in sql
    assert "graph_revision_at" in sql
    assert "graph_revision_at <= ledger_completed_at" in sql
