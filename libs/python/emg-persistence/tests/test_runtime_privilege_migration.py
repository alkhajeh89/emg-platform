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


def test_runtime_privilege_migrations_are_discovered_in_order() -> None:
    migrations = discover_migrations(
        default_migrations_dir(MigrationKind.POSTGRES), MigrationKind.POSTGRES
    )

    assert [(migration.version, migration.name) for migration in migrations[-6:]] == [
        (5, "runtime_least_privilege"),
        (6, "runtime_column_privileges"),
        (7, "audit_projector_privileges"),
        (8, "evidence_ledger_hardening"),
        (9, "scoped_runtime_privileges"),
        (10, "governed_entity_search"),
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


def test_audit_projector_privileges_are_column_scoped_and_schema_neutral() -> None:
    sql = (
        default_migrations_dir(MigrationKind.POSTGRES) / "V007__audit_projector_privileges.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(sql.split())

    assert "GRANT SELECT ON mutation_ledger, mutation_dispatch" in normalized
    assert (
        "GRANT UPDATE ( available_at, attempt_count, claim_owner, "
        "claim_expires_at, delivered_at ) ON mutation_dispatch" in normalized
    )
    assert "emg_knowledge_graph_app" not in normalized
    assert "ALTER TABLE" not in normalized
    assert "CREATE ROLE" not in normalized
    assert "UPDATE ON mutation_ledger" not in normalized


def test_future_kg_migrations_cannot_use_schema_wide_privilege_operations() -> None:
    migrations = discover_migrations(
        default_migrations_dir(MigrationKind.POSTGRES), MigrationKind.POSTGRES
    )
    forbidden = ("ALL TABLES IN SCHEMA", "ALL FUNCTIONS IN SCHEMA", "ALL SEQUENCES IN SCHEMA")

    for migration in migrations:
        if migration.version == 5:
            continue  # immutable historical exception, superseded by V009
        upper = migration.statements.upper()
        assert all(operation not in upper for operation in forbidden), migration.name


def test_v009_scopes_privileges_to_knowledge_graph_inventory() -> None:
    sql = (
        default_migrations_dir(MigrationKind.POSTGRES) / "V009__scoped_runtime_privileges.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(sql.split())

    assert "REVOKE ALL ON TABLE schema_migrations, tenants" in normalized
    assert "audit_events" not in normalized
    assert "audit_schema_migrations" not in normalized
    assert "identity_refresh_tokens" not in normalized
    assert "ALL TABLES IN SCHEMA" not in normalized
    assert "ALL FUNCTIONS IN SCHEMA" not in normalized
    assert "ALL SEQUENCES IN SCHEMA" not in normalized


def test_local_kg_role_seed_does_not_cross_stream_object_boundaries() -> None:
    seed = (
        default_migrations_dir(MigrationKind.POSTGRES).parents[6]
        / "tools/seed-data/postgres/005_knowledge_graph_role.sql"
    ).read_text(encoding="utf-8")
    upper = seed.upper()

    assert "GRANT ALL PRIVILEGES ON ALL TABLES" not in upper
    assert "GRANT ALL PRIVILEGES ON ALL FUNCTIONS" not in upper
    assert "GRANT ALL PRIVILEGES ON ALL SEQUENCES" not in upper
