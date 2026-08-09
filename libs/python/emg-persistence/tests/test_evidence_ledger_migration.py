from __future__ import annotations

from emg_persistence.migrate import default_migrations_dir
from emg_persistence.migrations import MigrationKind


def _migration() -> str:
    path = default_migrations_dir(MigrationKind.POSTGRES) / "V008__evidence_ledger_hardening.sql"
    return path.read_text(encoding="utf-8")


def test_v008_enforces_el10_constraints_without_rewriting_history() -> None:
    sql = _migration()
    normalized = " ".join(sql.split())

    assert "ALTER COLUMN prev_hash SET NOT NULL" in normalized
    assert "CHECK (seq >= 1)" in normalized
    assert "CHECK (prev_hash ~ '^[0-9a-f]{64}$')" in normalized
    assert "CHECK (entry_hash ~ '^[0-9a-f]{64}$')" in normalized
    assert "CHECK (seq <> 1 OR prev_hash = repeat('0', 64))" in normalized
    assert "UPDATE evidence_ledger SET" not in normalized
    assert "DELETE FROM evidence_ledger" not in normalized


def test_v008_installs_database_append_only_enforcement() -> None:
    sql = _migration()

    assert "CREATE FUNCTION reject_evidence_ledger_change()" in sql
    assert "CREATE TRIGGER evidence_ledger_append_only" in sql
    assert "BEFORE UPDATE OR DELETE ON evidence_ledger" in sql
    assert "RAISE EXCEPTION '% is append-only', TG_TABLE_NAME" in sql
    assert "REVOKE ALL ON FUNCTION reject_evidence_ledger_change() FROM PUBLIC" in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql
