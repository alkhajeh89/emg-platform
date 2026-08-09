"""ADR-041 PostgreSQL role bootstrap, Audit migration, and verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict

from ..migrate import audit_migrations_dir, default_migrations_dir, run_migrations
from ..migrations.discovery import discover_migrations
from ..migrations.executor import MigrationExecutor
from ..migrations.model import AppliedMigration, Migration, MigrationKind
from ..migrations.runner import MigrationRunner
from ..postgres.migration_executor import PostgresMigrationExecutor

AUDIT_HISTORY_TABLE = "audit_schema_migrations"
GOVERNED_DATABASE_ROLES = (
    "emg_audit_migrator",
    "emg_audit_app",
    "emg_audit_projector",
)
_AUDIT_TABLES = ("audit_events", "evidence_custody_events")
_AUDIT_COLUMNS = {
    "audit_events": (
        ("event_id", "text", True),
        ("source_principal", "text", True),
        ("sequence_number", "bigint", True),
        ("timestamp", "timestamp with time zone", True),
        ("ingest_time", "timestamp with time zone", True),
        ("prev_hash", "text", True),
        ("event_hash", "text", True),
        ("actor", "text", True),
        ("actor_type", "text", True),
        ("module", "text", True),
        ("action", "text", True),
        ("outcome", "text", True),
        ("correlation_id", "text", False),
        ("resource_type", "text", False),
        ("resource_id", "text", False),
        ("classification", "text", True),
        ("source_system", "text", True),
        ("source_component", "text", False),
        ("reason", "text", True),
        ("metadata", "jsonb", True),
        ("schema_version", "integer", True),
        ("provenance", "jsonb", False),
        ("tenant_id", "text", True),
    ),
    "evidence_custody_events": (
        ("custody_event_id", "text", True),
        ("source_principal", "text", True),
        ("chain_sequence", "bigint", True),
        ("custody_sequence", "bigint", True),
        ("transfer_timestamp", "timestamp with time zone", True),
        ("ingest_time", "timestamp with time zone", True),
        ("prev_hash", "text", True),
        ("event_hash", "text", True),
        ("evidence_id", "text", True),
        ("custody_action", "text", True),
        ("custodian", "text", True),
        ("prior_custodian", "text", False),
        ("transfer_reason", "text", True),
        ("classification", "text", True),
        ("correlation_id", "text", False),
        ("metadata", "jsonb", True),
    ),
}
_AUDIT_CONSTRAINTS = {
    "audit_events": {
        (
            "audit_events_actor_type_check",
            "c",
            "CHECK ((actor_type = ANY (ARRAY['human'::text, 'service'::text])))",
        ),
        (
            "audit_events_outcome_check",
            "c",
            "CHECK ((outcome = ANY " "(ARRAY['success'::text, 'denied'::text, 'error'::text])))",
        ),
        ("audit_events_pkey", "p", "PRIMARY KEY (source_principal, event_id)"),
        ("audit_events_sequence_number_key", "u", "UNIQUE (sequence_number)"),
    },
    "evidence_custody_events": {
        (
            "evidence_custody_events_custody_action_check",
            "c",
            "CHECK ((custody_action = ANY (ARRAY['acquire'::text, "
            "'transfer'::text, 'hold'::text, 'release'::text])))",
        ),
        (
            "evidence_custody_events_evidence_id_custody_sequence_key",
            "u",
            "UNIQUE (evidence_id, custody_sequence)",
        ),
        ("evidence_custody_events_chain_sequence_key", "u", "UNIQUE (chain_sequence)"),
        ("evidence_custody_events_pkey", "p", "PRIMARY KEY (source_principal, custody_event_id)"),
    },
}
_AUDIT_DEFAULTS = {
    "audit_events": {
        ("classification", "'INTERNAL'::text"),
        ("reason", "''::text"),
        ("metadata", "'{}'::jsonb"),
        ("schema_version", "1"),
        ("tenant_id", "'legacy-unscoped'::text"),
    },
    "evidence_custody_events": {
        ("transfer_reason", "''::text"),
        ("classification", "'INTERNAL'::text"),
        ("metadata", "'{}'::jsonb"),
    },
}


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
        _adopt_existing_audit_schema(cursor, schema_name)


def _audit_schema_signature(cursor: Any, schema_name: str, table: str) -> tuple[Any, Any, Any]:
    cursor.execute(
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = %s AND c.relkind = 'r' "
        "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
        (schema_name, table),
    )
    columns = tuple((str(row[0]), str(row[1]), bool(row[2])) for row in cursor.fetchall())
    cursor.execute(
        "SELECT conname, contype, pg_get_constraintdef(oid, false) FROM pg_constraint "
        "WHERE conrelid = %s::regclass ORDER BY conname",
        (f"{schema_name}.{table}",),
    )
    constraints = {(str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()}
    cursor.execute(
        "SELECT column_name, column_default FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_default IS NOT NULL",
        (schema_name, table),
    )
    defaults = {(str(row[0]), str(row[1])) for row in cursor.fetchall()}
    return columns, constraints, defaults


def _validate_adoptable_audit_schema(cursor: Any, schema_name: str) -> None:
    for table in _AUDIT_TABLES:
        columns, constraints, defaults = _audit_schema_signature(cursor, schema_name, table)
        if (
            columns != _AUDIT_COLUMNS[table]
            or constraints != _AUDIT_CONSTRAINTS[table]
            or defaults != _AUDIT_DEFAULTS[table]
        ):
            raise RuntimeError(
                f"existing {schema_name}.{table} does not match the governed "
                "Audit adoption contract"
            )


def _adopt_existing_audit_schema(cursor: Any, schema_name: str) -> None:
    cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s AND tablename = ANY(%s) "
        "ORDER BY tablename",
        (schema_name, list(_AUDIT_TABLES)),
    )
    existing = tuple(str(row[0]) for row in cursor.fetchall())
    if not existing:
        return
    if set(existing) != set(_AUDIT_TABLES):
        raise RuntimeError("existing Audit schema is incomplete; ownership adoption refused")
    _validate_adoptable_audit_schema(cursor, schema_name)
    for table in _AUDIT_TABLES:
        cursor.execute(
            sql.SQL("ALTER TABLE {}.{} OWNER TO emg_audit_migrator").format(
                sql.Identifier(schema_name), sql.Identifier(table)
            )
        )


def run_audit_migrations(
    migration_dsn: str,
) -> tuple[AppliedMigration, ...]:  # pragma: no cover - live PostgreSQL
    _dsn_credential(migration_dsn, "emg_audit_migrator")
    with psycopg.connect(migration_dsn) as connection:
        executor = PostgresMigrationExecutor(connection, history_table=AUDIT_HISTORY_TABLE)
        return run_migrations(executor, audit_migrations_dir())


def run_knowledge_graph_migrations(
    executor: MigrationExecutor,
) -> tuple[AppliedMigration, ...]:
    """Run KG migrations with an immutable-V005, stream-safe compatibility path."""
    migrations = discover_migrations(
        default_migrations_dir(MigrationKind.POSTGRES), MigrationKind.POSTGRES
    )
    by_version = {migration.version: migration for migration in migrations}
    if 5 not in by_version or 9 not in by_version:
        raise RuntimeError("Knowledge Graph migration compatibility requires V005 and V009")
    runner = MigrationRunner(executor)
    status = runner.status(migrations)
    applied_by_version = {migration.version: migration for migration in status.applied}
    if 5 in applied_by_version:
        return runner.run(migrations)
    if any(version > 5 for version in applied_by_version):
        raise RuntimeError("Knowledge Graph migration history has versions after missing V005")

    newly = list(runner.run(tuple(m for m in migrations if m.version < 5)))
    historical_v005 = by_version[5]
    scoped_v009 = by_version[9]
    compatibility_v005 = Migration(
        version=historical_v005.version,
        name=historical_v005.name,
        kind=historical_v005.kind,
        statements=scoped_v009.statements,
        checksum=historical_v005.checksum,
    )
    newly.append(executor.apply(compatibility_v005))
    newly.extend(runner.run(migrations))
    return tuple(newly)


def retry_dirty_knowledge_graph_v005(
    migration_dsn: str,
) -> AppliedMigration:  # pragma: no cover - live PostgreSQL
    """Atomically replace only the exact rolled-back V005 with scoped V009 SQL."""
    _dsn_credential(migration_dsn, "emg_knowledge_graph_migrator")
    migrations = discover_migrations(
        default_migrations_dir(MigrationKind.POSTGRES), MigrationKind.POSTGRES
    )
    by_version = {migration.version: migration for migration in migrations}
    historical_v005 = by_version.get(5)
    scoped_v009 = by_version.get(9)
    if historical_v005 is None or scoped_v009 is None:
        raise RuntimeError("Knowledge Graph V005 recovery requires canonical V005 and V009")

    with (
        psycopg.connect(migration_dsn) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT version, name, checksum, success, dirty FROM schema_migrations "
            "WHERE kind = 'postgres' ORDER BY version FOR UPDATE"
        )
        rows = cursor.fetchall()
        expected = [
            (
                migration.version,
                migration.name,
                migration.checksum,
                migration.version < 5,
                migration.version == 5,
            )
            for migration in migrations
            if migration.version <= 5
        ]
        if rows != expected:
            raise RuntimeError(
                "Knowledge Graph V005 recovery refused: history is not the exact "
                "canonical V001-V004 success plus dirty V005 state"
            )
        cursor.execute(scoped_v009.statements)
        cursor.execute(
            "UPDATE schema_migrations SET success = true, dirty = false, applied_at = now() "
            "WHERE kind = 'postgres' AND version = 5 AND checksum = %s "
            "AND success = false AND dirty = true RETURNING applied_at",
            (historical_v005.checksum,),
        )
        applied_at_row = cursor.fetchone()
        if cursor.rowcount != 1 or applied_at_row is None:
            raise RuntimeError("Knowledge Graph V005 recovery lost its dirty-history lock")
    return AppliedMigration(
        version=5,
        name=historical_v005.name,
        kind=MigrationKind.POSTGRES,
        checksum=historical_v005.checksum,
        applied_at=applied_at_row[0],
        success=True,
        dirty=False,
    )


def retry_dirty_audit_v001(
    migration_dsn: str,
) -> AppliedMigration:  # pragma: no cover - live PostgreSQL
    """Atomically reapply a transactionally rolled-back, exact Audit V001 failure."""
    _dsn_credential(migration_dsn, "emg_audit_migrator")
    migrations = discover_migrations(audit_migrations_dir(), MigrationKind.POSTGRES)
    if len(migrations) != 1 or migrations[0].version != 1:
        raise RuntimeError("Audit V001 recovery requires the canonical single V001 stream")
    migration = migrations[0]
    with (
        psycopg.connect(migration_dsn) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            sql.SQL(
                "SELECT version, name, checksum, success, dirty FROM {} "
                "WHERE kind = 'postgres' ORDER BY version FOR UPDATE"
            ).format(sql.Identifier(AUDIT_HISTORY_TABLE))
        )
        rows = cursor.fetchall()
        expected = [(1, migration.name, migration.checksum, False, True)]
        if rows != expected:
            raise RuntimeError(
                "Audit V001 recovery refused: history is not the exact "
                "canonical dirty V001 state"
            )
        cursor.execute("SELECT current_schema()")
        schema_row = cursor.fetchone()
        if schema_row is None or not isinstance(schema_row[0], str):
            raise RuntimeError("Audit V001 recovery cannot determine the current schema")
        schema_name = schema_row[0]
        _validate_adoptable_audit_schema(cursor, str(schema_name))
        cursor.execute(migration.statements)
        cursor.execute(
            sql.SQL(
                "UPDATE {} SET success = true, dirty = false, applied_at = now() "
                "WHERE kind = 'postgres' AND version = 1 AND checksum = %s "
                "AND success = false AND dirty = true RETURNING applied_at"
            ).format(sql.Identifier(AUDIT_HISTORY_TABLE)),
            (migration.checksum,),
        )
        applied_at_row = cursor.fetchone()
        if cursor.rowcount != 1 or applied_at_row is None:
            raise RuntimeError("Audit V001 recovery lost its dirty-history lock")
    return AppliedMigration(
        version=1,
        name=migration.name,
        kind=MigrationKind.POSTGRES,
        checksum=migration.checksum,
        applied_at=applied_at_row[0],
        success=True,
        dirty=False,
    )


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
