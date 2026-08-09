"""Live PostgreSQL proof for ADR-041 bootstrap, migration, and privileges."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from emg_persistence.migrate import default_migrations_dir, run_migrations
from emg_persistence.migrations import MigrationKind
from emg_persistence.migrations.errors import FailedMigrationError
from emg_persistence.postgres import PostgresMigrationExecutor
from emg_persistence.provisioning import (
    bootstrap_database_roles,
    retry_dirty_audit_v001,
    run_audit_migrations,
    validate_provisioned_databases,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.errors import InsufficientPrivilege

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)
ROOT = Path(__file__).resolve().parents[5]


def _dsn(database: str, user: str, password: str) -> str:
    assert _PG_DSN is not None
    values = conninfo_to_dict(_PG_DSN)
    values.update({"dbname": database, "user": user, "password": password})
    return make_conninfo(**values)


@pytest.fixture
def provisioned_database() -> Iterator[tuple[str, str, str, str]]:  # pragma: no cover
    assert _PG_DSN is not None
    database = f"rc1h_{uuid4().hex}"
    admin_values = conninfo_to_dict(_PG_DSN)
    admin_values["dbname"] = database
    admin_dsn = make_conninfo(**admin_values)
    with psycopg.connect(_PG_DSN, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))

    migrator_dsn = _dsn(database, "emg_audit_migrator", "rc1h-migrator-password")
    app_dsn = _dsn(database, "emg_audit_app", "rc1h-app-password")
    projector_dsn = _dsn(database, "emg_audit_projector", "rc1h-projector-password")
    try:
        yield admin_dsn, migrator_dsn, app_dsn, projector_dsn
    finally:
        with psycopg.connect(_PG_DSN, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


@requires_postgres
def test_database_bootstrap_audit_adoption_and_v007_least_privilege(
    provisioned_database: tuple[str, str, str, str], tmp_path: Path
) -> None:  # pragma: no cover
    admin_dsn, migrator_dsn, app_dsn, projector_dsn = provisioned_database
    role_dsns = {
        "emg_audit_migrator": migrator_dsn,
        "emg_audit_app": app_dsn,
        "emg_audit_projector": projector_dsn,
    }

    bootstrap_database_roles(admin_dsn, role_dsns)

    # Simulate a populated database initialized by the former local seed path,
    # executed by the bootstrap identity exactly as docker-entrypoint-initdb.d is.
    seed_names = (
        "001_audit_events.sql",
        "002_audit_provenance.sql",
        "003_evidence_custody.sql",
        "004_audit_reporting_indexes.sql",
        "006_audit_tenant.sql",
    )
    with psycopg.connect(admin_dsn) as connection:
        for name in seed_names:
            connection.execute(
                (ROOT / "tools/seed-data/postgres" / name).read_text(encoding="utf-8")
            )
        connection.execute(
            "INSERT INTO audit_events (event_id, source_principal, sequence_number, "
            "timestamp, ingest_time, prev_hash, event_hash, actor, actor_type, module, "
            "action, outcome, classification, source_system, reason, metadata, tenant_id) "
            "VALUES ('existing-event', 'existing-source', 1, clock_timestamp(), "
            "clock_timestamp(), %s, %s, 'actor', 'service', 'knowledge-graph', "
            "'create', 'success', 'INTERNAL', 'knowledge-graph', '', '{}'::jsonb, "
            "'tenant-existing')",
            ("0" * 64, "a" * 64),
        )
        connection.execute(
            "INSERT INTO evidence_custody_events (custody_event_id, source_principal, "
            "chain_sequence, custody_sequence, transfer_timestamp, ingest_time, prev_hash, "
            "event_hash, evidence_id, custody_action, custodian, metadata) VALUES "
            "('existing-custody', 'existing-source', 1, 1, clock_timestamp(), "
            "clock_timestamp(), %s, %s, 'evidence-1', 'acquire', 'custodian', '{}'::jsonb)",
            ("0" * 64, "b" * 64),
        )

    with pytest.raises(FailedMigrationError, match="must be owner"):
        run_audit_migrations(migrator_dsn)
    with psycopg.connect(migrator_dsn) as connection:
        history = connection.execute(
            "SELECT version, name, checksum, success, dirty FROM audit_schema_migrations"
        ).fetchall()
        assert len(history) == 1
        assert history[0][0:2] == (1, "audit_schema")
        assert history[0][3:5] == (False, True)
        canonical_checksum = history[0][2]
        connection.execute(
            "UPDATE audit_schema_migrations SET checksum = %s WHERE version = 1",
            ("0" * 64,),
        )
    with pytest.raises(RuntimeError, match="exact canonical dirty V001 state"):
        retry_dirty_audit_v001(migrator_dsn)
    with psycopg.connect(migrator_dsn) as connection:
        connection.execute(
            "UPDATE audit_schema_migrations SET checksum = %s WHERE version = 1",
            (canonical_checksum,),
        )

    # Stage 10 is idempotent and performs the bounded, schema-validated handoff.
    bootstrap_database_roles(admin_dsn, role_dsns)
    bootstrap_database_roles(admin_dsn, role_dsns)
    recovered = retry_dirty_audit_v001(migrator_dsn)
    assert recovered.name == "audit_schema"
    assert run_audit_migrations(migrator_dsn) == ()

    with psycopg.connect(migrator_dsn) as connection:
        row = connection.execute(
            "SELECT tenant_id, event_hash FROM audit_events WHERE event_id = 'existing-event'"
        ).fetchone()
        assert row == ("tenant-existing", "a" * 64)
        assert connection.execute(
            "SELECT event_hash FROM evidence_custody_events "
            "WHERE custody_event_id = 'existing-custody'"
        ).fetchone() == ("b" * 64,)
        assert connection.execute(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = current_schema() "
            "AND tablename IN ('audit_events', 'evidence_custody_events', "
            "'audit_schema_migrations') ORDER BY tablename"
        ).fetchall() == [
            ("audit_events", "emg_audit_migrator"),
            ("audit_schema_migrations", "emg_audit_migrator"),
            ("evidence_custody_events", "emg_audit_migrator"),
        ]
    with pytest.raises(RuntimeError, match="exact canonical dirty V001 state"):
        retry_dirty_audit_v001(migrator_dsn)

    with psycopg.connect(app_dsn) as connection, pytest.raises(InsufficientPrivilege):
        connection.execute("CREATE TABLE runtime_must_not_create_schema (id integer)")

    # Apply the existing Knowledge Graph ledger/dispatch foundation and V007
    # after bootstrap. V007 must now see the pre-created projector role.
    migrations = default_migrations_dir(MigrationKind.POSTGRES)
    for pattern in ("V00[1-4]__*.sql", "V007__*.sql"):
        for migration in migrations.glob(pattern):
            shutil.copy2(migration, tmp_path / migration.name)
    with psycopg.connect(admin_dsn) as connection:
        run_migrations(PostgresMigrationExecutor(connection), tmp_path)

    validate_provisioned_databases(migrator_dsn, admin_dsn)

    with psycopg.connect(projector_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM mutation_ledger").fetchone() == (0,)
        with pytest.raises(InsufficientPrivilege):
            connection.execute("CREATE TABLE projector_must_not_create_schema (id integer)")
        connection.rollback()
        with pytest.raises(InsufficientPrivilege):
            connection.execute("DELETE FROM mutation_dispatch")


@requires_postgres
def test_fresh_audit_database_migrates_without_adoption(
    provisioned_database: tuple[str, str, str, str],
) -> None:  # pragma: no cover
    admin_dsn, migrator_dsn, app_dsn, projector_dsn = provisioned_database
    bootstrap_database_roles(
        admin_dsn,
        {
            "emg_audit_migrator": migrator_dsn,
            "emg_audit_app": app_dsn,
            "emg_audit_projector": projector_dsn,
        },
    )

    assert [migration.name for migration in run_audit_migrations(migrator_dsn)] == ["audit_schema"]
    assert run_audit_migrations(migrator_dsn) == ()


@requires_postgres
def test_audit_adoption_rejects_schema_mismatch(
    provisioned_database: tuple[str, str, str, str],
) -> None:  # pragma: no cover
    admin_dsn, migrator_dsn, app_dsn, projector_dsn = provisioned_database
    role_dsns = {
        "emg_audit_migrator": migrator_dsn,
        "emg_audit_app": app_dsn,
        "emg_audit_projector": projector_dsn,
    }
    bootstrap_database_roles(admin_dsn, role_dsns)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("CREATE TABLE audit_events (event_id text PRIMARY KEY)")
        connection.execute("CREATE TABLE evidence_custody_events (custody_event_id text)")

    with pytest.raises(RuntimeError, match="does not match the governed Audit adoption contract"):
        bootstrap_database_roles(admin_dsn, role_dsns)

    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT tableowner FROM pg_tables WHERE tablename = 'audit_events'"
        ).fetchone() != ("emg_audit_migrator",)
