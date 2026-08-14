"""Live PostgreSQL proof for ADR-041 bootstrap, migration, and privileges."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from emg_identity.refresh_tokens import PostgresRefreshTokenStore
from emg_persistence.migrate import default_migrations_dir, run_migrations
from emg_persistence.migrations import MigrationKind
from emg_persistence.migrations.errors import FailedMigrationError
from emg_persistence.postgres import PostgresMigrationExecutor
from emg_persistence.provisioning import (
    InMemoryApprovedRecoveryAuthority,
    bootstrap_database_roles,
    reconcile_identity_recovery,
    retry_dirty_audit_v001,
    retry_dirty_knowledge_graph_v005,
    rotate_identity_recovery_generation,
    run_audit_migrations,
    run_identity_migrations,
    run_knowledge_graph_migrations,
    validate_provisioned_databases,
)
from emg_persistence.provisioning.database import _validate_identity_database
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.errors import InsufficientPrivilege

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)


def _reconcile_initial(identity_migrator_dsn: str) -> tuple[str, str]:
    """A8: establish the initial (generation, authority_revision) pair and
    record it via A6 reconciliation, as bootstrap requires before Stage-50
    may validate the recovery relation."""

    pair = InMemoryApprovedRecoveryAuthority().read_current()
    reconcile_identity_recovery(identity_migrator_dsn, pair.generation, pair.authority_revision)
    return pair.generation, pair.authority_revision


ROOT = Path(__file__).resolve().parents[5]


def _dsn(database: str, user: str, password: str) -> str:
    assert _PG_DSN is not None
    values = conninfo_to_dict(_PG_DSN)
    values.update({"dbname": database, "user": user, "password": password})
    return make_conninfo(**values)


def _bootstrap_role_dsns(
    admin_dsn: str, audit_migrator_dsn: str, audit_app_dsn: str, projector_dsn: str
) -> dict[str, str]:
    database = str(conninfo_to_dict(admin_dsn)["dbname"])
    return {
        "emg_audit_migrator": audit_migrator_dsn,
        "emg_audit_app": audit_app_dsn,
        "emg_audit_projector": projector_dsn,
        "emg_knowledge_graph_migrator": _dsn(
            database, "emg_knowledge_graph_migrator", "rc1h-kg-migrator-password"
        ),
        "emg_knowledge_graph_app": _dsn(
            database, "emg_knowledge_graph_app", "rc1h-kg-app-password"
        ),
        "emg_identity_migrator": _dsn(
            database, "emg_identity_migrator", "rc9-identity-migrator-password"
        ),
        "emg_identity_app": _dsn(database, "emg_identity_app", "rc9-identity-app-password"),
    }


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
    role_dsns = _bootstrap_role_dsns(admin_dsn, migrator_dsn, app_dsn, projector_dsn)

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

    identity_migrator_dsn = role_dsns["emg_identity_migrator"]
    run_identity_migrations(identity_migrator_dsn)
    _reconcile_initial(identity_migrator_dsn)
    validate_provisioned_databases(migrator_dsn, admin_dsn, identity_migrator_dsn)

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
        admin_dsn, _bootstrap_role_dsns(admin_dsn, migrator_dsn, app_dsn, projector_dsn)
    )

    assert [migration.name for migration in run_audit_migrations(migrator_dsn)] == ["audit_schema"]
    assert run_audit_migrations(migrator_dsn) == ()


@requires_postgres
def test_database_bootstrap_creates_and_converges_knowledge_graph_roles(
    provisioned_database: tuple[str, str, str, str],
) -> None:  # pragma: no cover
    admin_dsn, audit_migrator_dsn, audit_app_dsn, projector_dsn = provisioned_database
    role_dsns = _bootstrap_role_dsns(admin_dsn, audit_migrator_dsn, audit_app_dsn, projector_dsn)
    with psycopg.connect(admin_dsn) as connection:
        for role in ("emg_knowledge_graph_migrator", "emg_knowledge_graph_app"):
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))

    bootstrap_database_roles(admin_dsn, role_dsns)
    bootstrap_database_roles(admin_dsn, role_dsns)

    with psycopg.connect(admin_dsn) as connection:
        for role in ("emg_knowledge_graph_migrator", "emg_knowledge_graph_app"):
            assert connection.execute(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
                "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
                (role,),
            ).fetchone() == (True, False, False, False, False, False, False)
        assert connection.execute(
            "SELECT count(*) FROM pg_auth_members m "
            "JOIN pg_roles member ON member.oid = m.member "
            "WHERE member.rolname IN "
            "('emg_knowledge_graph_migrator', 'emg_knowledge_graph_app')"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT has_schema_privilege('emg_knowledge_graph_migrator', "
            "current_schema(), 'CREATE'), "
            "has_schema_privilege('emg_knowledge_graph_app', current_schema(), 'CREATE')"
        ).fetchone() == (True, False)

    with psycopg.connect(role_dsns["emg_knowledge_graph_migrator"]):
        pass
    with psycopg.connect(role_dsns["emg_knowledge_graph_app"]):
        pass

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("ALTER ROLE emg_knowledge_graph_migrator CREATEDB CREATEROLE INHERIT")
        connection.execute("ALTER ROLE emg_knowledge_graph_app CREATEDB CREATEROLE INHERIT")
    bootstrap_database_roles(admin_dsn, role_dsns)
    with psycopg.connect(admin_dsn) as connection:
        for role in ("emg_knowledge_graph_migrator", "emg_knowledge_graph_app"):
            assert connection.execute(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
                "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
                (role,),
            ).fetchone() == (True, False, False, False, False, False, False)

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("ALTER ROLE emg_knowledge_graph_app REPLICATION")
    with pytest.raises(RuntimeError, match="privileged attributes"):
        bootstrap_database_roles(admin_dsn, role_dsns)
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT rolreplication FROM pg_roles " "WHERE rolname = 'emg_knowledge_graph_app'"
        ).fetchone() == (True,)
        connection.execute("ALTER ROLE emg_knowledge_graph_app NOREPLICATION")


@requires_postgres
def test_audit_adoption_rejects_schema_mismatch(
    provisioned_database: tuple[str, str, str, str],
) -> None:  # pragma: no cover
    admin_dsn, migrator_dsn, app_dsn, projector_dsn = provisioned_database
    role_dsns = _bootstrap_role_dsns(admin_dsn, migrator_dsn, app_dsn, projector_dsn)
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


@requires_postgres
def test_identity_clean_migration_runtime_privileges_and_recovery_invalidation(
    provisioned_database: tuple[str, str, str, str],
) -> None:  # pragma: no cover
    admin_dsn, audit_migrator_dsn, audit_app_dsn, projector_dsn = provisioned_database
    role_dsns = _bootstrap_role_dsns(admin_dsn, audit_migrator_dsn, audit_app_dsn, projector_dsn)
    bootstrap_database_roles(admin_dsn, role_dsns)
    migrator_dsn = role_dsns["emg_identity_migrator"]
    runtime_dsn = role_dsns["emg_identity_app"]

    assert [migration.name for migration in run_identity_migrations(migrator_dsn)] == [
        "identity_refresh_state",
        "identity_recovery_state",
    ]
    assert run_identity_migrations(migrator_dsn) == ()
    authority = InMemoryApprovedRecoveryAuthority()
    initial_pair = authority.read_current()
    reconcile_identity_recovery(
        migrator_dsn, initial_pair.generation, initial_pair.authority_revision
    )

    store = PostgresRefreshTokenStore(runtime_dsn)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    store.register("runtime-family", "runtime-token-1", expires_at)
    assert store.rotate("runtime-family", "runtime-token-1", "runtime-token-2", expires_at)
    assert not store.rotate("runtime-family", "runtime-token-1", "runtime-token-3", expires_at)
    assert not store.family_is_active("runtime-family")

    with psycopg.connect(runtime_dsn) as connection:
        connection.execute(
            "INSERT INTO emg_identity.identity_refresh_token_families (family_hash) "
            "VALUES ('family')"
        )
        connection.execute(
            "INSERT INTO emg_identity.identity_refresh_tokens "
            "(token_hash, family_hash, status, expires_at) "
            "VALUES ('token', 'family', 'active', clock_timestamp() + interval '1 hour')"
        )
        connection.execute(
            "UPDATE emg_identity.identity_refresh_token_families "
            "SET revoked_at = clock_timestamp() WHERE family_hash = 'family'"
        )
        connection.execute(
            "UPDATE emg_identity.identity_refresh_tokens "
            "SET status = 'rotated', rotated_at = clock_timestamp() WHERE token_hash = 'token'"
        )
        connection.commit()
        for statement in (
            "DELETE FROM emg_identity.identity_refresh_tokens",
            "TRUNCATE emg_identity.identity_refresh_tokens",
            "CREATE TABLE emg_identity.runtime_ddl_forbidden (id integer)",
            "UPDATE emg_identity.identity_schema_migrations SET dirty = true",
            "UPDATE emg_identity.identity_refresh_tokens SET expires_at = clock_timestamp()",
        ):
            with pytest.raises(InsufficientPrivilege):
                connection.execute(statement)
            connection.rollback()

    with psycopg.connect(migrator_dsn) as connection:
        connection.execute(
            "UPDATE emg_identity.identity_refresh_token_families SET revoked_at = NULL"
        )
        connection.execute("UPDATE emg_identity.identity_refresh_tokens SET status = 'active'")
    rotated = rotate_identity_recovery_generation(authority)
    recovery_env = {
        **os.environ,
        "EMG_IDENTITY_RECOVERY_DSN": migrator_dsn,
        "EMG_IDENTITY_RECOVERY_GENERATION": rotated.generation,
        "EMG_IDENTITY_RECOVERY_AUTHORITY_REVISION": rotated.authority_revision,
        "EMG_BACKUP_PYTHON": str(ROOT / ".venv/bin/python"),
    }
    script = ROOT / "tools/backup/invalidate-identity-refresh-state.sh"
    subprocess.run([script], env=recovery_env, check=True)
    subprocess.run([script], env=recovery_env, check=True)  # crash/retry: idempotent (A6, A7(F))
    with psycopg.connect(migrator_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM emg_identity.identity_refresh_token_families "
            "WHERE revoked_at IS NULL"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM emg_identity.identity_refresh_tokens " "WHERE status <> 'revoked'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT reconciled_generation::text, reconciled_authority_revision "
            "FROM emg_identity.identity_recovery_state"
        ).fetchone() == (rotated.generation, rotated.authority_revision)
        _validate_identity_database(connection)
        connection.execute(
            "GRANT DELETE ON emg_identity.identity_refresh_tokens TO emg_identity_app"
        )
        with pytest.raises(RuntimeError, match="unexpected table-level grantee or privilege"):
            _validate_identity_database(connection)
        connection.rollback()

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("CREATE TABLE unrelated_identity_forbidden (id integer)")
        connection.execute("GRANT SELECT ON unrelated_identity_forbidden TO emg_identity_app")
    with (
        psycopg.connect(migrator_dsn) as connection,
        pytest.raises(RuntimeError, match="cross-schema"),
    ):
        _validate_identity_database(connection)


@requires_postgres
def test_identity_exact_legacy_adoption_preserves_rows_and_rejects_divergence(
    provisioned_database: tuple[str, str, str, str],
) -> None:  # pragma: no cover
    admin_dsn, audit_migrator_dsn, audit_app_dsn, projector_dsn = provisioned_database
    role_dsns = _bootstrap_role_dsns(admin_dsn, audit_migrator_dsn, audit_app_dsn, projector_dsn)
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "CREATE TABLE identity_refresh_token_families ("
            "family_hash TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL "
            "DEFAULT clock_timestamp(), revoked_at TIMESTAMPTZ)"
        )
        connection.execute(
            "CREATE TABLE identity_refresh_tokens (token_hash TEXT PRIMARY KEY, "
            "family_hash TEXT NOT NULL REFERENCES identity_refresh_token_families(family_hash), "
            "status TEXT NOT NULL CHECK (status IN ('active', 'rotated', 'revoked')), "
            "expires_at TIMESTAMPTZ NOT NULL, rotated_at TIMESTAMPTZ)"
        )
        connection.execute(
            "CREATE INDEX idx_identity_refresh_tokens_family "
            "ON identity_refresh_tokens (family_hash)"
        )
        connection.execute(
            "INSERT INTO identity_refresh_token_families (family_hash) VALUES ('legacy')"
        )
        connection.execute(
            "INSERT INTO identity_refresh_tokens "
            "(token_hash, family_hash, status, expires_at) VALUES "
            "('legacy-token', 'legacy', 'active', clock_timestamp() + interval '1 hour')"
        )

    bootstrap_database_roles(admin_dsn, role_dsns)
    run_identity_migrations(role_dsns["emg_identity_migrator"])
    with psycopg.connect(role_dsns["emg_identity_migrator"]) as connection:
        assert connection.execute(
            "SELECT family_hash FROM emg_identity.identity_refresh_token_families"
        ).fetchall() == [("legacy",)]
        legacy_table = connection.execute(
            "SELECT to_regclass('public.identity_refresh_tokens')"
        ).fetchone()
        assert legacy_table == (None,)


@requires_postgres
@pytest.mark.parametrize("state", ("partial", "divergent"))
def test_identity_legacy_adoption_fails_closed(
    provisioned_database: tuple[str, str, str, str], state: str
) -> None:  # pragma: no cover
    admin_dsn, audit_migrator_dsn, audit_app_dsn, projector_dsn = provisioned_database
    role_dsns = _bootstrap_role_dsns(admin_dsn, audit_migrator_dsn, audit_app_dsn, projector_dsn)
    with psycopg.connect(admin_dsn) as connection:
        if state == "partial":
            connection.execute(
                "CREATE TABLE identity_refresh_token_families (family_hash TEXT PRIMARY KEY)"
            )
        else:
            connection.execute(
                "CREATE TABLE identity_refresh_token_families (family_hash TEXT PRIMARY KEY)"
            )
            connection.execute(
                "CREATE TABLE identity_refresh_tokens (token_hash TEXT PRIMARY KEY, "
                "family_hash TEXT NOT NULL REFERENCES identity_refresh_token_families(family_hash))"
            )
    with pytest.raises(RuntimeError, match="Identity"):
        bootstrap_database_roles(admin_dsn, role_dsns)
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT to_regclass('public.identity_refresh_token_families') IS NOT NULL"
        ).fetchone() == (True,)


@requires_postgres
def test_fresh_colocated_streams_use_scoped_v005_compatibility(
    provisioned_database: tuple[str, str, str, str],
) -> None:  # pragma: no cover
    admin_dsn, audit_migrator_dsn, app_dsn, projector_dsn = provisioned_database
    bootstrap_database_roles(
        admin_dsn,
        _bootstrap_role_dsns(admin_dsn, audit_migrator_dsn, app_dsn, projector_dsn),
    )
    run_audit_migrations(audit_migrator_dsn)
    database = str(conninfo_to_dict(admin_dsn)["dbname"])
    kg_migrator_dsn = _dsn(database, "emg_knowledge_graph_migrator", "rc5-kg-migrator-password")
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            "'emg_knowledge_graph_migrator') THEN "
            "CREATE ROLE emg_knowledge_graph_migrator LOGIN; END IF; "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            "'emg_knowledge_graph_app') THEN "
            "CREATE ROLE emg_knowledge_graph_app LOGIN; END IF; END $$"
        )
        connection.execute(
            "ALTER ROLE emg_knowledge_graph_migrator LOGIN PASSWORD "
            "'rc5-kg-migrator-password' NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
        connection.execute(
            "ALTER ROLE emg_knowledge_graph_app LOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
        connection.execute("GRANT CREATE, USAGE ON SCHEMA public TO emg_knowledge_graph_migrator")
        connection.execute("CREATE TABLE identity_refresh_tokens (id text)")

    with psycopg.connect(kg_migrator_dsn) as connection:
        applied = run_knowledge_graph_migrations(PostgresMigrationExecutor(connection))
        assert [migration.version for migration in applied] == list(range(1, 11))
        assert run_knowledge_graph_migrations(PostgresMigrationExecutor(connection)) == ()
    with psycopg.connect(admin_dsn) as connection:
        assert connection.execute(
            "SELECT tableowner FROM pg_tables WHERE tablename = 'audit_schema_migrations'"
        ).fetchone() == ("emg_audit_migrator",)
        assert connection.execute(
            "SELECT tableowner FROM pg_tables WHERE tablename = 'identity_refresh_tokens'"
        ).fetchone() == (conninfo_to_dict(admin_dsn)["user"],)


@requires_postgres
def test_colocated_streams_recover_dirty_v005_without_cross_stream_mutation(
    provisioned_database: tuple[str, str, str, str], tmp_path: Path
) -> None:  # pragma: no cover
    admin_dsn, audit_migrator_dsn, app_dsn, projector_dsn = provisioned_database
    role_dsns = _bootstrap_role_dsns(admin_dsn, audit_migrator_dsn, app_dsn, projector_dsn)
    bootstrap_database_roles(admin_dsn, role_dsns)
    run_audit_migrations(audit_migrator_dsn)

    kg_migrator_dsn = _dsn(
        str(conninfo_to_dict(admin_dsn)["dbname"]),
        "emg_knowledge_graph_migrator",
        "rc5-kg-migrator-password",
    )
    with psycopg.connect(admin_dsn) as connection:
        connection.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            "'emg_knowledge_graph_migrator') THEN "
            "CREATE ROLE emg_knowledge_graph_migrator LOGIN; END IF; "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            "'emg_knowledge_graph_app') THEN "
            "CREATE ROLE emg_knowledge_graph_app LOGIN; END IF; END $$"
        )
        connection.execute(
            "ALTER ROLE emg_knowledge_graph_migrator LOGIN PASSWORD "
            "'rc5-kg-migrator-password' NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
        connection.execute(
            "ALTER ROLE emg_knowledge_graph_app LOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
        connection.execute("GRANT CREATE, USAGE ON SCHEMA public TO emg_knowledge_graph_migrator")
        connection.execute("CREATE TABLE identity_refresh_token_families (id text)")
        connection.execute("CREATE TABLE identity_refresh_tokens (id text)")
        audit_before = connection.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename IN "
            "('audit_events', 'audit_schema_migrations', 'evidence_custody_events') "
            "ORDER BY tablename"
        ).fetchall()
        identity_before = connection.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename IN "
            "('identity_refresh_token_families', 'identity_refresh_tokens') "
            "ORDER BY tablename"
        ).fetchall()
        audit_privileges_before = connection.execute(
            "SELECT has_table_privilege('emg_audit_app', 'audit_events', 'SELECT'), "
            "has_table_privilege('emg_audit_app', 'audit_events', 'INSERT'), "
            "has_table_privilege('emg_audit_app', 'audit_events', 'UPDATE')"
        ).fetchone()

    migrations = default_migrations_dir(MigrationKind.POSTGRES)
    for pattern in ("V00[1-4]__*.sql", "V005__*.sql"):
        for migration in migrations.glob(pattern):
            shutil.copy2(migration, tmp_path / migration.name)
    with psycopg.connect(kg_migrator_dsn) as connection:
        with pytest.raises(FailedMigrationError, match="audit_schema_migrations"):
            run_migrations(PostgresMigrationExecutor(connection), tmp_path)
        history = connection.execute(
            "SELECT version, name, checksum, success, dirty FROM schema_migrations "
            "ORDER BY version"
        ).fetchall()
        assert [(row[0], row[1], row[3], row[4]) for row in history] == [
            (1, "baseline", True, False),
            (2, "projection_checkpoints", True, False),
            (3, "mutation_idempotency", True, False),
            (4, "mutation_ledger", True, False),
            (5, "runtime_least_privilege", False, True),
        ]
        v005_checksum = history[4][2]
        connection.execute(
            "UPDATE schema_migrations SET checksum = %s WHERE version = 5", ("0" * 64,)
        )
    with pytest.raises(RuntimeError, match="exact canonical V001-V004 success"):
        retry_dirty_knowledge_graph_v005(kg_migrator_dsn)
    with psycopg.connect(kg_migrator_dsn) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum = %s WHERE version = 5", (v005_checksum,)
        )

    retry_dirty_knowledge_graph_v005(kg_migrator_dsn)
    with pytest.raises(RuntimeError, match="exact canonical V001-V004 success"):
        retry_dirty_knowledge_graph_v005(kg_migrator_dsn)
    with psycopg.connect(kg_migrator_dsn) as connection:
        applied = run_knowledge_graph_migrations(PostgresMigrationExecutor(connection))
        assert [migration.version for migration in applied] == [6, 7, 8, 9, 10]

    identity_migrator_dsn = role_dsns["emg_identity_migrator"]
    run_identity_migrations(identity_migrator_dsn)
    _reconcile_initial(identity_migrator_dsn)
    validate_provisioned_databases(audit_migrator_dsn, kg_migrator_dsn, identity_migrator_dsn)
    with psycopg.connect(admin_dsn) as connection:
        assert (
            connection.execute(
                "SELECT tableowner FROM pg_tables WHERE tablename IN "
                "('audit_events', 'audit_schema_migrations', 'evidence_custody_events') "
                "ORDER BY tablename"
            ).fetchall()
            == audit_before
        )
        assert (
            connection.execute(
                "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename IN "
                "('identity_refresh_token_families', 'identity_refresh_tokens') "
                "ORDER BY tablename"
            ).fetchall()
            == identity_before
        )
        assert (
            connection.execute(
                "SELECT has_table_privilege('emg_audit_app', 'audit_events', 'SELECT'), "
                "has_table_privilege('emg_audit_app', 'audit_events', 'INSERT'), "
                "has_table_privilege('emg_audit_app', 'audit_events', 'UPDATE')"
            ).fetchone()
            == audit_privileges_before
        )
        assert connection.execute(
            "SELECT success, dirty, checksum FROM schema_migrations WHERE version = 5"
        ).fetchone() == (True, False, v005_checksum)
