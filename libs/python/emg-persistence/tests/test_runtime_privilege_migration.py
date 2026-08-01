from emg_persistence.migrate import default_migrations_dir
from emg_persistence.migrations import MigrationKind, discover_migrations

_EXISTING_POSTGRES_CHECKSUMS = {
    1: "8a751cb3e1ec25c8db840a3a2de519902fbed284cab3b44eaa47dd615ac8b81e",
    2: "51ebe39f01f6465094324d3fcdee0f0c0645f4853aedb272b80a2c90bdc086f2",
    3: "99fdcdea35ed032f3e530f6118ed27ff2e0a282afa7ff2dc045e8830a06d4001",
    4: "73f2eeef7196edc9056b303ca85850505bb7d0d7fc112ef4a8581344e0ee4cd4",
    5: "83693fb50dcc6575051ff737626cec094358f421999b8710fd868d22efd6c981",
}


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


def test_runtime_column_privilege_migration_is_discovered_after_v005() -> None:
    migrations = discover_migrations(
        default_migrations_dir(MigrationKind.POSTGRES), MigrationKind.POSTGRES
    )

    assert [(migration.version, migration.name) for migration in migrations[-2:]] == [
        (5, "runtime_least_privilege"),
        (6, "runtime_column_privileges"),
    ]


def test_existing_postgres_migration_checksums_are_unchanged() -> None:
    migrations = discover_migrations(
        default_migrations_dir(MigrationKind.POSTGRES), MigrationKind.POSTGRES
    )

    assert {
        migration.version: migration.checksum for migration in migrations if migration.version <= 5
    } == _EXISTING_POSTGRES_CHECKSUMS


def test_runtime_column_privileges_match_repository_updates() -> None:
    sql = (
        default_migrations_dir(MigrationKind.POSTGRES) / "V006__runtime_column_privileges.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(sql.split())

    assert (
        "REVOKE UPDATE ON TABLE graph_head, outbox, projection_checkpoints, "
        "mutation_idempotency, mutation_dispatch FROM emg_knowledge_graph_app" in normalized
    )
    assert (
        "GRANT UPDATE ( head_revision_number, head_content_hash, updated_at ) "
        "ON TABLE graph_head TO emg_knowledge_graph_app" in normalized
    )
    assert (
        "GRANT UPDATE ( state, mutation_id, revision_number, content_hash, "
        "receipt_json, mutation_result_json, expires_at ) ON TABLE "
        "mutation_idempotency TO emg_knowledge_graph_app" in normalized
    )
    assert (
        "GRANT UPDATE ( claim_owner, claim_expires_at, attempt_count, "
        "source_system_id, source_timeline, source_commit_lsn, source_tx_index, "
        "delivered_at ) ON TABLE mutation_dispatch TO emg_knowledge_graph_app" in normalized
    )
    update_grants = tuple(
        statement.strip()
        for statement in normalized.split(";")
        if statement.strip().startswith("GRANT UPDATE")
    )
    assert len(update_grants) == 3
    assert all("ON TABLE outbox" not in statement for statement in update_grants)
    assert all("ON TABLE projection_checkpoints" not in statement for statement in update_grants)
    assert "ALTER TABLE" not in normalized
    assert "CREATE ROLE" not in normalized
