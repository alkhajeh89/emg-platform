"""DB-backed migration-framework integration tests (Sprint 2).

These require live datastores and are **skipped** unless the corresponding env
vars are set; they run in the CI ``persistence`` job (PostgreSQL 16 + Neo4j 5
Community), not in the no-DB ``quality`` job. They exercise the real
transactional PostgreSQL executor and the idempotent Neo4j executor against the
packaged baseline migrations.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from emg_persistence import PersistenceSettings
from emg_persistence.migrate import migration_status, run_migrations
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


@pytest.fixture
def pg_executor() -> Iterator[object]:  # pragma: no cover - runs only with a live DB
    from emg_persistence.postgres import PostgresMigrationExecutor, connect

    settings = PersistenceSettings(postgres_dsn=_PG_DSN)
    conn = connect(settings)
    with conn.cursor() as cur:
        cur.execute(_RESET_SCHEMA_SQL)
        cur.execute(_CREATE_SCHEMA_SQL)
        cur.execute(_SET_SEARCH_PATH_SQL)
    conn.commit()
    try:
        yield PostgresMigrationExecutor(conn)
    finally:
        with conn.cursor() as cur:
            cur.execute(_RESET_SCHEMA_SQL)
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
    assert [a.version for a in applied] == [1, 2, 3, 4, 5]
    assert applied[0].name == "baseline"
    assert applied[1].name == "projection_checkpoints"
    assert applied[2].name == "mutation_idempotency"
    assert applied[3].name == "mutation_ledger"
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
