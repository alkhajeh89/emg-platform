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
from emg_persistence.postgres import PostgresMigrationExecutor
from emg_persistence.provisioning import (
    bootstrap_database_roles,
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
    bootstrap_database_roles(admin_dsn, role_dsns)

    # Simulate a populated database initialized by the former local seed path,
    # but owned by the now-canonical migration principal.
    seed_names = (
        "001_audit_events.sql",
        "002_audit_provenance.sql",
        "003_evidence_custody.sql",
        "004_audit_reporting_indexes.sql",
        "006_audit_tenant.sql",
    )
    with psycopg.connect(migrator_dsn) as connection:
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

    applied = run_audit_migrations(migrator_dsn)
    assert [item.name for item in applied] == ["audit_schema"]
    assert run_audit_migrations(migrator_dsn) == ()

    with psycopg.connect(migrator_dsn) as connection:
        row = connection.execute(
            "SELECT tenant_id, event_hash FROM audit_events WHERE event_id = 'existing-event'"
        ).fetchone()
        assert row == ("tenant-existing", "a" * 64)

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
