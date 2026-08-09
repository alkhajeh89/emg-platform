"""DB-backed migration-framework integration tests (Sprint 2).

These require live datastores and are **skipped** unless the corresponding env
vars are set; they run in the CI ``persistence`` job (PostgreSQL 16 + Neo4j 5
Community), not in the no-DB ``quality`` job. They exercise the real
transactional PostgreSQL executor and the idempotent Neo4j executor against the
packaged baseline migrations.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from emg_persistence import PersistenceSettings
from emg_persistence.migrate import default_migrations_dir, migration_status, run_migrations
from emg_persistence.migrations import (
    ChecksumMismatchError,
    DirtyMigrationError,
    FailedMigrationError,
    MigrationKind,
)

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
_NEO4J_URI = os.environ.get("EMG_PERSISTENCE_TEST_NEO4J_URI")

requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)
requires_neo4j = pytest.mark.skipif(
    not _NEO4J_URI, reason="requires EMG_PERSISTENCE_TEST_NEO4J_URI"
)

# Dedicated schema so this file's schema_migrations rows (and its synthetic
# t_ok/t_x tables) can never collide with -- or be dropped by -- the shared
# public.schema_migrations table every other integration file reads/writes.
# The version numbers used below (1, 2) intentionally reuse the same integers
# as the real baseline migrations; isolation here is by schema, not by
# renumbering, so the dirty/checksum/forward-only assertions stay unchanged.
_TEST_SCHEMA = "migration_test"
_RESET_SCHEMA_SQL = f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"
_CREATE_SCHEMA_SQL = f"CREATE SCHEMA {_TEST_SCHEMA}"
_SET_SEARCH_PATH_SQL = f"SET search_path TO {_TEST_SCHEMA}"
_APP_ROLE = "emg_knowledge_graph_app"
_MIGRATOR_ROLE = "emg_knowledge_graph_migrator"
_CREATE_APP_ROLE_SQL = f"CREATE ROLE {_APP_ROLE} NOLOGIN"
_CREATE_MIGRATOR_ROLE_SQL = f"CREATE ROLE {_MIGRATOR_ROLE} NOLOGIN"
_DROP_APP_ROLE_SQL = f"DROP ROLE IF EXISTS {_APP_ROLE}"
_DROP_MIGRATOR_ROLE_SQL = f"DROP ROLE IF EXISTS {_MIGRATOR_ROLE}"


@pytest.fixture
def pg_executor() -> Iterator[object]:  # pragma: no cover - runs only with a live DB
    from emg_persistence.postgres import PostgresMigrationExecutor, connect

    settings = PersistenceSettings(postgres_dsn=_PG_DSN)
    conn = connect(settings)
    created_roles: set[str] = set()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rolname FROM pg_roles WHERE rolname IN (%s, %s)",
                (_APP_ROLE, _MIGRATOR_ROLE),
            )
            existing_roles = {row[0] for row in cur.fetchall()}
            if _APP_ROLE not in existing_roles:
                cur.execute(_CREATE_APP_ROLE_SQL)
                created_roles.add(_APP_ROLE)
            if _MIGRATOR_ROLE not in existing_roles:
                cur.execute(_CREATE_MIGRATOR_ROLE_SQL)
                created_roles.add(_MIGRATOR_ROLE)
            cur.execute(_RESET_SCHEMA_SQL)
            cur.execute(_CREATE_SCHEMA_SQL)
            cur.execute(f"GRANT CREATE, USAGE ON SCHEMA {_TEST_SCHEMA} TO {_MIGRATOR_ROLE}")
            cur.execute(_SET_SEARCH_PATH_SQL)
        conn.commit()
        yield PostgresMigrationExecutor(conn)
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(_RESET_SCHEMA_SQL)
            if _APP_ROLE in created_roles:
                cur.execute(_DROP_APP_ROLE_SQL)
            if _MIGRATOR_ROLE in created_roles:
                cur.execute(_DROP_MIGRATOR_ROLE_SQL)
        conn.commit()
        conn.close()


@pytest.fixture
def neo4j_executor() -> Iterator[object]:  # pragma: no cover - runs only with a live DB
    from emg_persistence.neo4j import Neo4jMigrationExecutor, create_driver

    settings = PersistenceSettings(
        neo4j_uri=_NEO4J_URI,
        neo4j_user=os.environ.get("EMG_PERSISTENCE_TEST_NEO4J_USER"),
        neo4j_password=os.environ.get("EMG_PERSISTENCE_TEST_NEO4J_PASSWORD"),
    )
    driver = create_driver(settings)
    with driver.session() as session:
        session.run("MATCH (m:SchemaMigration) DETACH DELETE m")
    try:
        yield Neo4jMigrationExecutor(driver)
    finally:
        with driver.session() as session:
            session.run("MATCH (m:SchemaMigration) DETACH DELETE m")
        driver.close()


@requires_postgres
def test_postgres_baseline_applies_and_is_idempotent(pg_executor) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    applied = run_migrations(pg_executor)
    assert [a.version for a in applied] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert applied[0].name == "baseline"
    assert applied[1].name == "projection_checkpoints"
    assert applied[2].name == "mutation_idempotency"
    assert applied[3].name == "mutation_ledger"
    assert applied[4].name == "runtime_least_privilege"
    assert applied[5].name == "runtime_column_privileges"
    assert applied[6].name == "audit_projector_privileges"
    assert applied[7].name == "evidence_ledger_hardening"
    assert run_migrations(pg_executor) == ()
    assert migration_status(pg_executor).is_up_to_date is True

    connection = pg_executor._connection
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_schema_privilege(" "'emg_knowledge_graph_app', current_schema(), 'CREATE')"
        )
        assert cursor.fetchone() == (False,)
        cursor.execute(
            "SELECT tableowner FROM pg_tables "
            "WHERE schemaname = current_schema() AND tablename = 'tenants'"
        )
        assert cursor.fetchone() == ("emg_knowledge_graph_migrator",)
        cursor.execute(
            "SELECT "
            "has_table_privilege('emg_knowledge_graph_app', "
            "current_schema() || '.tenants', 'SELECT'), "
            "has_table_privilege('emg_knowledge_graph_app', "
            "current_schema() || '.tenants', 'DELETE'), "
            "has_table_privilege('emg_knowledge_graph_app', "
            "current_schema() || '.mutation_idempotency', 'DELETE')"
        )
        assert cursor.fetchone() == (True, False, True)
        cursor.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'evidence_ledger' AND column_name = 'prev_hash'"
        )
        assert cursor.fetchone() == ("NO",)
        cursor.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'evidence_ledger'::regclass "
            "AND conname LIKE 'ck_evidence_ledger_%' ORDER BY conname"
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "ck_evidence_ledger_entry_hash_format",
            "ck_evidence_ledger_genesis_prev_hash",
            "ck_evidence_ledger_prev_hash_format",
            "ck_evidence_ledger_seq_positive",
        ]
        cursor.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = 'evidence_ledger'::regclass "
            "AND NOT tgisinternal"
        )
        assert cursor.fetchone() == ("evidence_ledger_append_only",)
        cursor.execute(
            "SELECT "
            "has_table_privilege('emg_knowledge_graph_app', "
            "current_schema() || '.evidence_ledger', 'SELECT'), "
            "has_table_privilege('emg_knowledge_graph_app', "
            "current_schema() || '.evidence_ledger', 'INSERT'), "
            "has_table_privilege('emg_knowledge_graph_app', "
            "current_schema() || '.evidence_ledger', 'UPDATE'), "
            "has_table_privilege('emg_knowledge_graph_app', "
            "current_schema() || '.evidence_ledger', 'DELETE'), "
            "has_function_privilege('emg_knowledge_graph_app', "
            "current_schema() || '.reject_evidence_ledger_change()', 'EXECUTE')"
        )
        assert cursor.fetchone() == (True, True, False, False, False)


@requires_postgres
def test_el10_migration_fails_closed_without_rewriting_invalid_history(
    pg_executor, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    migrations = default_migrations_dir(MigrationKind.POSTGRES)
    for migration in sorted(migrations.glob("V00[1-7]__*.sql")):
        shutil.copy2(migration, tmp_path / migration.name)
    run_migrations(pg_executor, tmp_path)

    connection = pg_executor._connection
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO evidence_ledger (tenant_id, seq, evidence_id, prev_hash, "
            "entry_hash, source, locator, source_principal, captured_at, payload) "
            "VALUES ('invalid-history', 0, 'evidence-1', NULL, %s, 'pdf', "
            "'invalid.pdf', 'svc-evidence', clock_timestamp(), '{}'::jsonb)",
            ("a" * 64,),
        )

    hardening = migrations / "V008__evidence_ledger_hardening.sql"
    shutil.copy2(hardening, tmp_path / hardening.name)
    with pytest.raises(FailedMigrationError, match="evidence_ledger contains seq < 1"):
        run_migrations(pg_executor, tmp_path)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT seq, prev_hash, entry_hash FROM evidence_ledger "
            "WHERE tenant_id = 'invalid-history'"
        )
        assert cursor.fetchone() == (0, None, "a" * 64)


@requires_postgres
def test_runtime_role_update_privileges_match_repository_operations(pg_executor) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    from psycopg.errors import InsufficientPrivilege

    run_migrations(pg_executor)
    connection = pg_executor._connection
    mutation_id = uuid4()
    tenant_id = "runtime-privilege-tenant"

    # Seed the immutable ledger and dispatch rows without exercising their
    # semantic triggers because this test verifies privileges only.
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
        cursor.execute(
            "INSERT INTO mutation_ledger (mutation_id, tenant_id, principal_id, "
            "principal_kind, idempotency_key, command_fingerprint, "
            "fingerprint_version, command_schema_version, operation, status, "
            "graph_revision, graph_content_hash, write_receipt, mutation_result, "
            "audit_intents, resource_count, requested_at, graph_revision_at, "
            "replay_expires_at) VALUES (%s, %s, 'runtime-principal', 'service', "
            "'runtime-privilege-ledger', %s, 1, 1, 'create_entity', 'succeeded', "
            "1, 'hash-1', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 1, "
            "clock_timestamp() - interval '1 second', "
            "clock_timestamp() - interval '1 second', "
            "clock_timestamp() + interval '1 hour')",
            (mutation_id, tenant_id, "a" * 64),
        )
        cursor.execute(
            "INSERT INTO mutation_dispatch (mutation_id, tenant_id, channel) "
            "VALUES (%s, %s, 'audit')",
            (mutation_id, tenant_id),
        )

    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {_APP_ROLE}")
    connection.commit()
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("INSERT INTO tenants (tenant_id) VALUES (%s)", (tenant_id,))
            cursor.execute(
                "INSERT INTO graph_revisions (tenant_id, revision_number, content_hash, "
                "principal_id, principal_kind, node_count, edge_count, graph_json) "
                "VALUES (%s, 1, 'hash-1', 'runtime-principal', 'service', 0, 0, '{}'::jsonb)",
                (tenant_id,),
            )
            cursor.execute(
                "INSERT INTO graph_head "
                "(tenant_id, head_revision_number, head_content_hash) "
                "VALUES (%s, 1, 'hash-1')",
                (tenant_id,),
            )
            cursor.execute(
                "INSERT INTO outbox (event_id, tenant_id, revision_number, content_hash, "
                "event_type, schema_version, idempotency_key, payload) "
                "VALUES (%s, %s, 1, 'hash-1', 'graph.updated', 1, "
                "'runtime-privilege-event', '{}'::jsonb)",
                (uuid4(), tenant_id),
            )
            cursor.execute(
                "INSERT INTO projection_checkpoints "
                "(tenant_id, revision_number, event_id) VALUES (%s, 1, %s)",
                (tenant_id, uuid4()),
            )
            cursor.execute(
                "INSERT INTO mutation_idempotency "
                "(tenant_id, principal_id, idempotency_key, operation_type, "
                "state, command_fingerprint, fingerprint_version, "
                "command_schema_version, requested_at, expires_at) "
                "VALUES (%s, 'runtime-principal', 'runtime-privilege-key', "
                "'create_entity', 'pending', %s, 1, 1, clock_timestamp(), "
                "clock_timestamp() + interval '1 hour')",
                (tenant_id, "a" * 64),
            )

            cursor.execute(
                "UPDATE graph_head SET head_revision_number = 2, "
                "head_content_hash = 'hash-2', updated_at = clock_timestamp() "
                "WHERE tenant_id = %s",
                (tenant_id,),
            )
            assert cursor.rowcount == 1
            cursor.execute(
                "UPDATE mutation_idempotency SET state = 'succeeded', "
                "mutation_id = %s, revision_number = 1, content_hash = 'hash-1', "
                "receipt_json = '{}'::jsonb, mutation_result_json = '{}'::jsonb, "
                "expires_at = expires_at + interval '1 hour' "
                "WHERE tenant_id = %s AND principal_id = 'runtime-principal' "
                "AND idempotency_key = 'runtime-privilege-key'",
                (mutation_id, tenant_id),
            )
            assert cursor.rowcount == 1
            cursor.execute(
                "UPDATE mutation_dispatch SET claim_owner = 'runtime-worker', "
                "claim_expires_at = clock_timestamp() + interval '1 minute', "
                "attempt_count = attempt_count + 1 "
                "WHERE mutation_id = %s AND channel = 'audit'",
                (mutation_id,),
            )
            assert cursor.rowcount == 1
            cursor.execute(
                "UPDATE mutation_dispatch SET source_system_id = 'runtime-system', "
                "source_timeline = 1, source_commit_lsn = '0/10', source_tx_index = 0 "
                "WHERE mutation_id = %s AND channel = 'audit'",
                (mutation_id,),
            )
            assert cursor.rowcount == 1
            cursor.execute(
                "UPDATE mutation_dispatch SET delivered_at = clock_timestamp(), "
                "claim_owner = NULL, claim_expires_at = NULL "
                "WHERE mutation_id = %s AND channel = 'audit'",
                (mutation_id,),
            )
            assert cursor.rowcount == 1
            cursor.execute(
                "SELECT head_revision_number FROM graph_head WHERE tenant_id = %s", (tenant_id,)
            )
            assert cursor.fetchone() == (2,)
            cursor.execute(
                "DELETE FROM mutation_idempotency "
                "WHERE tenant_id = %s AND principal_id = 'runtime-principal' "
                "AND idempotency_key = 'runtime-privilege-key'",
                (tenant_id,),
            )
            assert cursor.rowcount == 1

        with (
            pytest.raises(InsufficientPrivilege),
            connection.transaction(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE mutation_dispatch SET available_at = clock_timestamp() "
                "WHERE mutation_id = %s AND channel = 'audit'",
                (mutation_id,),
            )
        with (
            pytest.raises(InsufficientPrivilege),
            connection.transaction(),
            connection.cursor() as cursor,
        ):
            cursor.execute("UPDATE outbox SET published_at = clock_timestamp()")
        with (
            pytest.raises(InsufficientPrivilege),
            connection.transaction(),
            connection.cursor() as cursor,
        ):
            cursor.execute("UPDATE projection_checkpoints SET processed_at = clock_timestamp()")
    finally:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        connection.commit()


@requires_postgres
def test_postgres_checksum_immutability(pg_executor, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    (tmp_path / "V001__x.sql").write_text("CREATE TABLE t_x (id int);", encoding="utf-8")
    run_migrations(pg_executor, tmp_path)
    # Edit the already-applied migration on disk -> checksum changes -> reject.
    (tmp_path / "V001__x.sql").write_text("CREATE TABLE t_x (id bigint);", encoding="utf-8")
    with pytest.raises(ChecksumMismatchError):
        run_migrations(pg_executor, tmp_path)


@requires_postgres
def test_postgres_transactional_rollback_and_dirty_halt(pg_executor, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    (tmp_path / "V001__ok.sql").write_text("CREATE TABLE t_ok (id int);", encoding="utf-8")
    (tmp_path / "V002__broken.sql").write_text("CREATE TABLE t_ok (bad syntax", encoding="utf-8")
    with pytest.raises(FailedMigrationError):
        run_migrations(pg_executor, tmp_path)
    # V002 rolled back atomically; a dirty marker halts the next run.
    with pytest.raises(DirtyMigrationError):
        run_migrations(pg_executor, tmp_path)


@requires_neo4j
def test_neo4j_baseline_applies_and_is_idempotent(neo4j_executor) -> None:  # type: ignore[no-untyped-def]  # pragma: no cover
    applied = run_migrations(neo4j_executor)
    assert [a.version for a in applied] == [1]
    assert applied[0].kind is MigrationKind.NEO4J
    assert run_migrations(neo4j_executor) == ()  # idempotent
