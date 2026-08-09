from __future__ import annotations

from emg_persistence.migrate import audit_migrations_dir
from emg_persistence.provisioning import AUDIT_HISTORY_TABLE, GOVERNED_DATABASE_ROLES


def test_database_bootstrap_declares_only_adr_041_roles() -> None:
    assert GOVERNED_DATABASE_ROLES == (
        "emg_audit_migrator",
        "emg_audit_app",
        "emg_audit_projector",
    )
    assert AUDIT_HISTORY_TABLE == "audit_schema_migrations"


def test_audit_migration_preserves_seed_semantics_and_runtime_restriction() -> None:
    sql = (audit_migrations_dir() / "V001__audit_schema.sql").read_text(encoding="utf-8")
    normalized = " ".join(sql.split())

    assert "CREATE TABLE IF NOT EXISTS audit_events" in normalized
    assert "CREATE TABLE IF NOT EXISTS evidence_custody_events" in normalized
    assert "PRIMARY KEY (source_principal, event_id)" in normalized
    assert "UNIQUE (evidence_id, custody_sequence)" in normalized
    assert "tenant_id TEXT NOT NULL DEFAULT 'legacy-unscoped'" in normalized
    assert "ALTER TABLE audit_events OWNER TO emg_audit_migrator" in normalized
    assert "ALTER TABLE evidence_custody_events OWNER TO emg_audit_migrator" in normalized
    assert (
        "GRANT INSERT, SELECT ON audit_events, evidence_custody_events TO emg_audit_app"
        in normalized
    )
    assert "REVOKE CREATE ON SCHEMA public FROM emg_audit_app" in normalized
    assert "DROP TABLE" not in normalized
    assert "TRUNCATE audit_events" not in normalized
    assert "CREATE ROLE" not in normalized
    assert "PASSWORD" not in normalized


def test_production_audit_migration_stream_does_not_reference_local_seed_sql() -> None:
    for path in audit_migrations_dir().glob("*.sql"):
        sql = path.read_text(encoding="utf-8")
        assert "tools/seed-data" not in sql
        assert "local_dev" not in sql
