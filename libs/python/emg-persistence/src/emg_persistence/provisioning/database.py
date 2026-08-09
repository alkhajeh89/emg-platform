"""ADR-041 PostgreSQL role bootstrap, Audit migration, and verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict

from ..migrate import audit_migrations_dir, run_migrations
from ..migrations.model import AppliedMigration
from ..postgres.migration_executor import PostgresMigrationExecutor

AUDIT_HISTORY_TABLE = "audit_schema_migrations"
GOVERNED_DATABASE_ROLES = (
    "emg_audit_migrator",
    "emg_audit_app",
    "emg_audit_projector",
)


def _dsn_credential(dsn: str, expected_role: str) -> str:
    parsed = conninfo_to_dict(dsn)
    username = parsed.get("user", "")
    password = parsed.get("password", "")
    if username != expected_role:
        raise RuntimeError(f"PostgreSQL DSN must authenticate as {expected_role}")
    if not isinstance(password, str) or not password:
        raise RuntimeError(f"PostgreSQL DSN for {expected_role} must contain a credential")
    return password


def bootstrap_database_roles(
    admin_dsn: str, role_dsns: Mapping[str, str]
) -> None:  # pragma: no cover - live PostgreSQL
    """Create/converge only ADR-041's governed LOGIN roles.

    Passwords are taken from environment-owned DSNs; neither credential
    material nor DSNs are logged or returned.
    """

    if set(role_dsns) != set(GOVERNED_DATABASE_ROLES):
        raise RuntimeError("database bootstrap requires exactly the ADR-041 governed roles")
    passwords = {role: _dsn_credential(role_dsns[role], role) for role in GOVERNED_DATABASE_ROLES}
    with psycopg.connect(admin_dsn) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        current_user_row = cursor.fetchone()
        if current_user_row is None:
            raise RuntimeError("PostgreSQL bootstrap administrator cannot be determined")
        current_user = current_user_row[0]
        if current_user in GOVERNED_DATABASE_ROLES:
            raise RuntimeError("database bootstrap administrator cannot be a runtime role")
        for role in GOVERNED_DATABASE_ROLES:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role))
                )
            else:
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role))
                )
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(passwords[role])
                )
            )
        cursor.execute("SELECT current_schema()")
        schema_row = cursor.fetchone()
        if schema_row is None or not isinstance(schema_row[0], str):
            raise RuntimeError("PostgreSQL current schema cannot be determined")
        schema_name = schema_row[0]
        cursor.execute(
            sql.SQL("GRANT CREATE, USAGE ON SCHEMA {} TO emg_audit_migrator").format(
                sql.Identifier(schema_name)
            )
        )
        cursor.execute(
            sql.SQL("REVOKE CREATE ON SCHEMA {} FROM emg_audit_app, emg_audit_projector").format(
                sql.Identifier(schema_name)
            )
        )


def run_audit_migrations(
    migration_dsn: str,
) -> tuple[AppliedMigration, ...]:  # pragma: no cover - live PostgreSQL
    _dsn_credential(migration_dsn, "emg_audit_migrator")
    with psycopg.connect(migration_dsn) as connection:
        executor = PostgresMigrationExecutor(connection, history_table=AUDIT_HISTORY_TABLE)
        return run_migrations(executor, audit_migrations_dir())


def _role_attributes(connection: Connection[Any], role: str) -> tuple[bool, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
            "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
            (role,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"required PostgreSQL role {role} is absent")
    return tuple(bool(value) for value in row)


def _validate_role_attributes(connection: Connection[Any]) -> None:
    for role in GOVERNED_DATABASE_ROLES:
        attributes = _role_attributes(connection, role)
        if attributes != (True, False, False, False, False, False, False):
            raise RuntimeError(f"PostgreSQL role {role} has non-conformant attributes")


def _validate_audit_database(connection: Connection[Any]) -> None:
    _validate_role_attributes(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename, tableowner FROM pg_tables "
            "WHERE schemaname = current_schema() AND tablename IN "
            "('audit_events', 'evidence_custody_events', %s) ORDER BY tablename",
            (AUDIT_HISTORY_TABLE,),
        )
        owners: dict[str, str] = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
        expected = {
            "audit_events": "emg_audit_migrator",
            AUDIT_HISTORY_TABLE: "emg_audit_migrator",
            "evidence_custody_events": "emg_audit_migrator",
        }
        if owners != expected:
            raise RuntimeError("Audit schema objects are absent or not owned by migrator")
        cursor.execute(
            "SELECT has_schema_privilege('emg_audit_app', current_schema(), 'CREATE'), "
            "has_table_privilege('emg_audit_app', 'audit_events', 'SELECT'), "
            "has_table_privilege('emg_audit_app', 'audit_events', 'INSERT'), "
            "has_table_privilege('emg_audit_app', 'audit_events', 'UPDATE'), "
            "has_table_privilege('emg_audit_app', 'audit_events', 'DELETE'), "
            "has_table_privilege('emg_audit_app', 'evidence_custody_events', 'SELECT'), "
            "has_table_privilege('emg_audit_app', 'evidence_custody_events', 'INSERT'), "
            "has_table_privilege('emg_audit_app', 'evidence_custody_events', 'UPDATE'), "
            "has_table_privilege('emg_audit_app', 'evidence_custody_events', 'DELETE')"
        )
        if cursor.fetchone() != (False, True, True, False, False, True, True, False, False):
            raise RuntimeError("Audit runtime privileges do not match ADR-041")


def _validate_projector_database(connection: Connection[Any]) -> None:
    _validate_role_attributes(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_schema_privilege('emg_audit_projector', current_schema(), 'USAGE'), "
            "has_schema_privilege('emg_audit_projector', current_schema(), 'CREATE'), "
            "has_table_privilege('emg_audit_projector', 'mutation_ledger', 'SELECT'), "
            "has_table_privilege('emg_audit_projector', 'mutation_ledger', 'UPDATE'), "
            "has_table_privilege('emg_audit_projector', 'mutation_dispatch', 'SELECT'), "
            "has_table_privilege('emg_audit_projector', 'mutation_dispatch', 'DELETE')"
        )
        if cursor.fetchone() != (True, False, True, False, True, False):
            raise RuntimeError("Audit Projector table privileges do not match V007")
        cursor.execute(
            "SELECT column_name FROM information_schema.column_privileges "
            "WHERE grantee = 'emg_audit_projector' AND table_schema = current_schema() "
            "AND table_name = 'mutation_dispatch' AND privilege_type = 'UPDATE' "
            "ORDER BY column_name"
        )
        if tuple(row[0] for row in cursor.fetchall()) != (
            "attempt_count",
            "available_at",
            "claim_expires_at",
            "claim_owner",
            "delivered_at",
        ):
            raise RuntimeError("Audit Projector UPDATE privileges do not match V007")


def validate_provisioned_databases(
    audit_migration_dsn: str, knowledge_graph_migration_dsn: str
) -> None:  # pragma: no cover - live PostgreSQL
    _dsn_credential(audit_migration_dsn, "emg_audit_migrator")
    with psycopg.connect(audit_migration_dsn) as audit_connection:
        _validate_audit_database(audit_connection)
    with psycopg.connect(knowledge_graph_migration_dsn) as graph_connection:
        _validate_projector_database(graph_connection)
