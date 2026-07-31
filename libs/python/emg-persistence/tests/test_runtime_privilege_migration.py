from emg_persistence.migrate import default_migrations_dir
from emg_persistence.migrations import MigrationKind


def test_runtime_privilege_migration_removes_runtime_ddl_and_ownership() -> None:
    sql = (
        default_migrations_dir(MigrationKind.POSTGRES) / "V005__runtime_least_privilege.sql"
    ).read_text(encoding="utf-8")

    assert "REVOKE CREATE ON SCHEMA %I FROM emg_knowledge_graph_app" in sql
    assert "OWNER TO emg_knowledge_graph_migrator" in sql
    assert "REVOKE ALL ON ALL FUNCTIONS" in sql
    assert "GRANT SELECT, INSERT ON tenants, graph_revisions" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON graph_head" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON mutation_idempotency" in sql
    assert "DELETE ON graph_revisions" not in sql
