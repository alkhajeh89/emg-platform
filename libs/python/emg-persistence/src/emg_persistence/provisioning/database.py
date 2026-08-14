"""ADR-041 PostgreSQL role bootstrap, Audit migration, and verification."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict

from ..migrate import (
    audit_migrations_dir,
    default_migrations_dir,
    identity_migrations_dir,
    run_migrations,
)
from ..migrations.discovery import discover_migrations
from ..migrations.executor import MigrationExecutor
from ..migrations.model import AppliedMigration, Migration, MigrationKind
from ..migrations.runner import MigrationRunner
from ..postgres.migration_executor import PostgresMigrationExecutor

AUDIT_HISTORY_TABLE = "audit_schema_migrations"
IDENTITY_SCHEMA = "emg_identity"
IDENTITY_HISTORY_RELATION = f"{IDENTITY_SCHEMA}.identity_schema_migrations"
GOVERNED_DATABASE_ROLES = (
    "emg_audit_migrator",
    "emg_audit_app",
    "emg_audit_projector",
    "emg_knowledge_graph_migrator",
    "emg_knowledge_graph_app",
    "emg_identity_migrator",
    "emg_identity_app",
)
_GOVERNED_ROLE_ATTRIBUTES = (True, False, False, False, False, False, False)
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
IDENTITY_RECOVERY_TABLE = "identity_recovery_state"
_IDENTITY_TABLES = ("identity_refresh_token_families", "identity_refresh_tokens")
_IDENTITY_EXPECTED_TABLE_GRANTS: dict[str, tuple[tuple[str, str], ...]] = {
    "identity_refresh_token_families": (
        ("emg_identity_app", "INSERT"),
        ("emg_identity_app", "SELECT"),
    ),
    "identity_refresh_tokens": (
        ("emg_identity_app", "INSERT"),
        ("emg_identity_app", "SELECT"),
    ),
    IDENTITY_RECOVERY_TABLE: (("emg_identity_app", "SELECT"),),
}
_IDENTITY_EXPECTED_COLUMN_GRANTS: dict[str, tuple[tuple[str, str], ...]] = {
    "identity_refresh_token_families": (("emg_identity_app", "revoked_at"),),
    "identity_refresh_tokens": (
        ("emg_identity_app", "rotated_at"),
        ("emg_identity_app", "status"),
    ),
    IDENTITY_RECOVERY_TABLE: (),
}
_IDENTITY_COLUMNS = {
    "identity_refresh_token_families": (
        ("family_hash", "text", True),
        ("created_at", "timestamp with time zone", True),
        ("revoked_at", "timestamp with time zone", False),
    ),
    "identity_refresh_tokens": (
        ("token_hash", "text", True),
        ("family_hash", "text", True),
        ("status", "text", True),
        ("expires_at", "timestamp with time zone", True),
        ("rotated_at", "timestamp with time zone", False),
    ),
}
_IDENTITY_CONSTRAINTS = {
    "identity_refresh_token_families": {
        ("p", "PRIMARY KEY (family_hash)"),
    },
    "identity_refresh_tokens": {
        ("p", "PRIMARY KEY (token_hash)"),
        (
            "f",
            "FOREIGN KEY (family_hash) REFERENCES identity_refresh_token_families(family_hash)",
        ),
        (
            "c",
            "CHECK ((status = ANY (ARRAY['active'::text, 'rotated'::text, 'revoked'::text])))",
        ),
    },
}
_IDENTITY_DEFAULTS = {
    "identity_refresh_token_families": {("created_at", "clock_timestamp()")},
    "identity_refresh_tokens": set(),
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


def _create_or_converge_role(cursor: Any, role: str, password: str) -> None:
    attributes = _role_attributes_from_cursor(cursor, role)
    if attributes is None:
        cursor.execute(
            sql.SQL(
                "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
            ).format(sql.Identifier(role))
        )
    else:
        if attributes[1] or attributes[5] or attributes[6]:
            raise RuntimeError(
                f"PostgreSQL role {role} has privileged attributes that "
                "bootstrap cannot safely converge"
            )
        cursor.execute(
            sql.SQL("ALTER ROLE {} WITH LOGIN NOCREATEDB NOCREATEROLE NOINHERIT").format(
                sql.Identifier(role)
            )
        )
    cursor.execute(
        sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(password))
    )
    effective_attributes = _role_attributes_from_cursor(cursor, role)
    if effective_attributes != _GOVERNED_ROLE_ATTRIBUTES:
        raise RuntimeError(f"PostgreSQL role {role} has non-conformant attributes")


@contextmanager
def _temporary_role_membership(cursor: Any, role: str) -> Iterator[None]:
    """Grant the connected administrator SET ROLE on ``role`` only for the
    statement(s) that require it, then revoke it before the enclosing
    transaction commits.

    PostgreSQL 16 no longer grants a CREATEROLE administrator implicit
    membership in roles it creates (unlike PostgreSQL < 16), so operations
    such as ``CREATE SCHEMA ... AUTHORIZATION`` and ``ALTER ... OWNER TO``
    fail for a non-superuser bootstrap administrator (e.g. Cloud SQL's
    default admin) unless it is first granted membership. The bootstrap
    administrator must not retain standing membership in a governed
    runtime role, so the grant is scoped to this block only. If the
    wrapped statement raises, the enclosing transaction is rolled back by
    the caller and the revoke below is intentionally skipped -- attempting
    it would itself fail against the now-aborted transaction.
    """
    cursor.execute("SELECT current_user")
    admin_row = cursor.fetchone()
    assert admin_row is not None
    admin = admin_row[0]
    cursor.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(admin)))
    yield
    cursor.execute(sql.SQL("REVOKE {} FROM {}").format(sql.Identifier(role), sql.Identifier(admin)))


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
            _create_or_converge_role(cursor, role, passwords[role])
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
        cursor.execute(
            sql.SQL("GRANT CREATE, USAGE ON SCHEMA {} TO emg_knowledge_graph_migrator").format(
                sql.Identifier(schema_name)
            )
        )
        cursor.execute(
            sql.SQL("REVOKE CREATE ON SCHEMA {} FROM emg_knowledge_graph_app").format(
                sql.Identifier(schema_name)
            )
        )
        _bootstrap_identity_schema(cursor)
        _adopt_existing_audit_schema(cursor, schema_name)
        _adopt_existing_identity_schema(cursor)


def _bootstrap_identity_schema(cursor: Any) -> None:
    cursor.execute(
        "SELECT r.rolname FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner "
        "WHERE n.nspname = %s",
        (IDENTITY_SCHEMA,),
    )
    owner = cursor.fetchone()
    if owner is not None and owner != ("emg_identity_migrator",):
        raise RuntimeError("existing emg_identity schema is not owned by emg_identity_migrator")
    # REVOKE below requires ownership-level authority on every run, not only
    # at initial creation, so the temporary membership spans the schema's
    # full owner-privileged statement sequence.
    with _temporary_role_membership(cursor, "emg_identity_migrator"):
        if owner is None:
            cursor.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION emg_identity_migrator").format(
                    sql.Identifier(IDENTITY_SCHEMA)
                )
            )
        cursor.execute(
            sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(IDENTITY_SCHEMA))
        )
        cursor.execute(
            sql.SQL("REVOKE CREATE ON SCHEMA {} FROM emg_identity_app").format(
                sql.Identifier(IDENTITY_SCHEMA)
            )
        )


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


def _identity_schema_signature(cursor: Any, schema_name: str, table: str) -> tuple[Any, Any, Any]:
    columns, named_constraints, defaults = _audit_schema_signature(cursor, schema_name, table)
    constraints = {
        (
            constraint[1],
            constraint[2]
            .replace(f"REFERENCES {schema_name}.", "REFERENCES ")
            .replace("REFERENCES public.", "REFERENCES "),
        )
        for constraint in named_constraints
    }
    return columns, constraints, defaults


def _validate_identity_index(cursor: Any, schema_name: str) -> None:
    cursor.execute(
        "SELECT i.relname, am.amname, ix.indisunique, ix.indisprimary, "
        "array_agg(a.attname ORDER BY key.ordinality) "
        "FROM pg_class t JOIN pg_namespace n ON n.oid = t.relnamespace "
        "JOIN pg_index ix ON ix.indrelid = t.oid "
        "JOIN pg_class i ON i.oid = ix.indexrelid "
        "JOIN pg_am am ON am.oid = i.relam "
        "JOIN unnest(ix.indkey) WITH ORDINALITY AS key(attnum, ordinality) ON true "
        "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = key.attnum "
        "WHERE n.nspname = %s AND t.relname = 'identity_refresh_tokens' "
        "AND NOT ix.indisprimary GROUP BY i.relname, am.amname, ix.indisunique, ix.indisprimary",
        (schema_name,),
    )
    indexes = cursor.fetchall()
    if indexes != [("idx_identity_refresh_tokens_family", "btree", False, False, ["family_hash"])]:
        raise RuntimeError(
            f"existing {schema_name}.identity_refresh_tokens indexes do not match "
            "the governed Identity adoption contract"
        )


def _validate_identity_table_security_state(
    cursor: Any, schema_name: str, table: str, *, allow_empty_grants: bool = False
) -> None:
    """P0-1: reject any unexpected security-material catalog state (A11).

    Covers grantee/ACL (including PUBLIC), column ACL, ownership, user
    triggers, RLS/FORCE RLS, policies, rules, and security labels. When
    ``allow_empty_grants`` is True (pre-adoption legacy-table validation),
    the object's non-owner grants must be either empty or exactly the
    governed baseline; a divergent legacy grant is rejected, never silently
    normalized (D-6, A11). When False (governed/Stage-50 validation), the
    non-owner grants and ownership must exactly match the governed baseline.
    """

    qualified = f"{schema_name}.{table}"
    cursor.execute(
        "SELECT tableowner FROM pg_tables WHERE schemaname = %s AND tablename = %s",
        (schema_name, table),
    )
    owner_row = cursor.fetchone()
    if owner_row is None:
        raise RuntimeError(f"{qualified} is absent")
    owner = owner_row[0]
    cursor.execute(
        "SELECT grantee, privilege_type FROM information_schema.table_privileges "
        "WHERE table_schema = %s AND table_name = %s AND grantee <> %s "
        "ORDER BY grantee, privilege_type",
        (schema_name, table, owner),
    )
    table_grants = cursor.fetchall()
    expected_table_grants = list(_IDENTITY_EXPECTED_TABLE_GRANTS[table])
    if table_grants != expected_table_grants and not (allow_empty_grants and not table_grants):
        raise RuntimeError(f"{qualified} has an unexpected table-level grantee or privilege")
    cursor.execute(
        "SELECT grantee, column_name FROM information_schema.column_privileges "
        "WHERE table_schema = %s AND table_name = %s AND grantee <> %s "
        "AND privilege_type = 'UPDATE' ORDER BY grantee, column_name",
        (schema_name, table, owner),
    )
    column_grants = cursor.fetchall()
    expected_column_grants = list(_IDENTITY_EXPECTED_COLUMN_GRANTS[table])
    if column_grants != expected_column_grants and not (allow_empty_grants and not column_grants):
        raise RuntimeError(f"{qualified} has an unexpected column-level grantee")
    cursor.execute(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal",
        (qualified,),
    )
    if cursor.fetchall():
        raise RuntimeError(f"{qualified} has an unexpected user-defined trigger")
    cursor.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
        (qualified,),
    )
    if cursor.fetchone() != (False, False):
        raise RuntimeError(f"{qualified} has unexpected row-level security state")
    cursor.execute(
        "SELECT policyname FROM pg_policies WHERE schemaname = %s AND tablename = %s",
        (schema_name, table),
    )
    if cursor.fetchall():
        raise RuntimeError(f"{qualified} has an unexpected row-security policy")
    cursor.execute(
        "SELECT rulename FROM pg_rules WHERE schemaname = %s AND tablename = %s",
        (schema_name, table),
    )
    if cursor.fetchall():
        raise RuntimeError(f"{qualified} has an unexpected rule")
    cursor.execute(
        "SELECT label FROM pg_seclabel WHERE objoid = %s::regclass "
        "AND classoid = 'pg_class'::regclass",
        (qualified,),
    )
    if cursor.fetchall():
        raise RuntimeError(f"{qualified} has an unexpected security label")
    if not allow_empty_grants and owner != "emg_identity_migrator":
        raise RuntimeError(f"{qualified} owner is not emg_identity_migrator")


def _validate_identity_schema(
    cursor: Any, schema_name: str, *, allow_empty_grants: bool = False
) -> None:
    for table in _IDENTITY_TABLES:
        columns, constraints, defaults = _identity_schema_signature(cursor, schema_name, table)
        if (
            columns != _IDENTITY_COLUMNS[table]
            or constraints != _IDENTITY_CONSTRAINTS[table]
            or defaults != _IDENTITY_DEFAULTS[table]
        ):
            raise RuntimeError(
                f"existing {schema_name}.{table} does not match the governed "
                "Identity adoption contract"
            )
        _validate_identity_table_security_state(
            cursor, schema_name, table, allow_empty_grants=allow_empty_grants
        )
    _validate_identity_index(cursor, schema_name)


def _identity_tables_in_schema(cursor: Any, schema_name: str) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s AND tablename = ANY(%s) "
        "ORDER BY tablename",
        (schema_name, list(_IDENTITY_TABLES)),
    )
    return tuple(str(row[0]) for row in cursor.fetchall())


def _adopt_existing_identity_schema(cursor: Any) -> None:
    # The entire body introspects and (on the legacy-adoption path) alters
    # objects owned by emg_identity_migrator, none of which are visible or
    # alterable by a non-superuser administrator without that role's
    # privileges -- the schema has no PUBLIC grants (see
    # _bootstrap_identity_schema). Temporary membership spans the whole
    # function rather than only the DDL statements so every introspection
    # path (governed-adoption check, legacy-adoption check, and the no-op
    # "nothing to adopt" path) sees consistent, correct results.
    with _temporary_role_membership(cursor, "emg_identity_migrator"):
        legacy = _identity_tables_in_schema(cursor, "public")
        governed = _identity_tables_in_schema(cursor, IDENTITY_SCHEMA)
        cursor.execute("SELECT to_regclass(%s)", (IDENTITY_HISTORY_RELATION,))
        history_exists = cursor.fetchone() != (None,)
        if governed:
            if set(governed) != set(_IDENTITY_TABLES) or legacy:
                raise RuntimeError(
                    "Identity schema state is partial or conflicting; adoption refused"
                )
            _validate_identity_schema(cursor, IDENTITY_SCHEMA)
            cursor.execute(
                "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = %s "
                "AND tablename = ANY(%s) ORDER BY tablename",
                (IDENTITY_SCHEMA, list(_IDENTITY_TABLES)),
            )
            if {str(row[1]) for row in cursor.fetchall()} != {"emg_identity_migrator"}:
                raise RuntimeError("governed Identity tables have conflicting ownership")
            return
        if not legacy:
            return
        if history_exists:
            raise RuntimeError("legacy Identity tables conflict with existing migration history")
        if set(legacy) != set(_IDENTITY_TABLES):
            raise RuntimeError("legacy Identity schema is incomplete; adoption refused")
        _validate_identity_schema(cursor, "public", allow_empty_grants=True)
        cursor.execute(
            "SELECT count(DISTINCT tableowner) FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename = ANY(%s)",
            (list(_IDENTITY_TABLES),),
        )
        if cursor.fetchone() != (1,):
            raise RuntimeError("legacy Identity tables have ambiguous ownership")
        for table in _IDENTITY_TABLES:
            cursor.execute(
                sql.SQL("ALTER TABLE public.{} SET SCHEMA {}").format(
                    sql.Identifier(table), sql.Identifier(IDENTITY_SCHEMA)
                )
            )
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} OWNER TO emg_identity_migrator").format(
                    sql.Identifier(IDENTITY_SCHEMA), sql.Identifier(table)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE ALL ON TABLE {}.{} FROM PUBLIC, emg_identity_app").format(
                    sql.Identifier(IDENTITY_SCHEMA), sql.Identifier(table)
                )
            )


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


def run_identity_migrations(
    migration_dsn: str,
) -> tuple[AppliedMigration, ...]:  # pragma: no cover - live PostgreSQL
    _dsn_credential(migration_dsn, "emg_identity_migrator")
    with psycopg.connect(migration_dsn) as connection:
        executor = PostgresMigrationExecutor(connection, history_table=IDENTITY_HISTORY_RELATION)
        return run_migrations(executor, identity_migrations_dir())


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


def _role_attributes_from_cursor(cursor: Any, role: str) -> tuple[bool, ...] | None:
    cursor.execute(
        "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
        "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
        (role,),
    )
    row = cursor.fetchone()
    return None if row is None else tuple(bool(value) for value in row)


def _role_attributes(connection: Connection[Any], role: str) -> tuple[bool, ...]:
    with connection.cursor() as cursor:
        attributes = _role_attributes_from_cursor(cursor, role)
    if attributes is None:
        raise RuntimeError(f"required PostgreSQL role {role} is absent")
    return attributes


def _validate_role_attributes(connection: Connection[Any]) -> None:
    for role in GOVERNED_DATABASE_ROLES:
        attributes = _role_attributes(connection, role)
        if attributes != _GOVERNED_ROLE_ATTRIBUTES:
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


def _validate_identity_database(connection: Connection[Any]) -> None:
    _validate_role_attributes(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT r.rolname FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner "
            "WHERE n.nspname = %s",
            (IDENTITY_SCHEMA,),
        )
        if cursor.fetchone() != ("emg_identity_migrator",):
            raise RuntimeError("Identity schema is absent or not owned by its migrator")
        _validate_identity_schema(cursor, IDENTITY_SCHEMA)
        cursor.execute(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = %s "
            "AND tablename IN ('identity_refresh_token_families', "
            "'identity_refresh_tokens', 'identity_schema_migrations') ORDER BY tablename",
            (IDENTITY_SCHEMA,),
        )
        if cursor.fetchall() != [
            ("identity_refresh_token_families", "emg_identity_migrator"),
            ("identity_refresh_tokens", "emg_identity_migrator"),
            ("identity_schema_migrations", "emg_identity_migrator"),
        ]:
            raise RuntimeError("Identity objects are absent or not owned by their migrator")
        cursor.execute(
            "SELECT member.rolname, parent.rolname FROM pg_auth_members membership "
            "JOIN pg_roles member ON member.oid = membership.member "
            "JOIN pg_roles parent ON parent.oid = membership.roleid "
            "WHERE member.rolname IN ('emg_identity_migrator', 'emg_identity_app') "
            "ORDER BY member.rolname, parent.rolname"
        )
        if cursor.fetchall():
            raise RuntimeError("Identity roles have prohibited role membership")
        cursor.execute(
            "SELECT version, success, dirty FROM "
            "emg_identity.identity_schema_migrations WHERE kind = 'postgres' "
            "ORDER BY version"
        )
        if cursor.fetchall() != [(1, True, False), (2, True, False)]:
            raise RuntimeError("Identity migration history is incomplete or non-conformant")
        cursor.execute(
            "SELECT has_schema_privilege('emg_identity_app', %s, 'USAGE'), "
            "has_schema_privilege('emg_identity_app', %s, 'CREATE'), "
            "has_schema_privilege('public', %s, 'USAGE'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_token_families', 'SELECT'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_token_families', 'INSERT'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_token_families', 'UPDATE'), "
            "has_column_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_token_families', 'revoked_at', 'UPDATE'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_token_families', 'DELETE'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_token_families', 'TRUNCATE'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_tokens', 'SELECT'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_tokens', 'INSERT'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_tokens', 'UPDATE'), "
            "has_column_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_tokens', 'status', 'UPDATE'), "
            "has_column_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_tokens', 'rotated_at', 'UPDATE'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_tokens', 'DELETE'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_refresh_tokens', 'TRUNCATE'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_schema_migrations', 'SELECT'), "
            "has_table_privilege('emg_identity_app', "
            "'emg_identity.identity_schema_migrations', 'UPDATE')",
            (IDENTITY_SCHEMA, IDENTITY_SCHEMA, IDENTITY_SCHEMA),
        )
        if cursor.fetchone() != (
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
            False,
        ):
            raise RuntimeError("Identity runtime privileges do not match ADR-043")
        cursor.execute(
            "SELECT table_name, column_name FROM information_schema.column_privileges "
            "WHERE grantee = 'emg_identity_app' AND table_schema = %s "
            "AND privilege_type = 'UPDATE' ORDER BY table_name, column_name",
            (IDENTITY_SCHEMA,),
        )
        if cursor.fetchall() != [
            ("identity_refresh_token_families", "revoked_at"),
            ("identity_refresh_tokens", "rotated_at"),
            ("identity_refresh_tokens", "status"),
        ]:
            raise RuntimeError("Identity runtime column privileges do not match ADR-043")
        cursor.execute(
            "SELECT n.nspname, c.relname, acl.privilege_type FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, "
            "acldefault('r', c.relowner))) acl "
            "JOIN pg_roles grantee ON grantee.oid = acl.grantee "
            "WHERE grantee.rolname = 'emg_identity_app' AND n.nspname <> %s "
            "UNION ALL "
            "SELECT n.nspname, '', acl.privilege_type FROM pg_namespace n "
            "CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl, "
            "acldefault('n', n.nspowner))) acl "
            "JOIN pg_roles grantee ON grantee.oid = acl.grantee "
            "WHERE grantee.rolname = 'emg_identity_app' AND n.nspname <> %s "
            "ORDER BY 1, 2, 3",
            (IDENTITY_SCHEMA, IDENTITY_SCHEMA),
        )
        if cursor.fetchall():
            raise RuntimeError("Identity runtime has unintended cross-schema table authority")
        _validate_identity_recovery_state(cursor)


def _validate_identity_recovery_state(cursor: Any) -> None:
    """A11/Stage-50: validate the Amendment 1 recovery relation exactly.

    Proves the relation exists, is owned by the migrator, carries the exact
    singleton constraint, has no security-material divergence (ACLs,
    triggers, RLS, policies, rules, security labels -- via the same P0-1
    helper used for the refresh-state tables), grants runtime exactly
    SELECT with no mutation/DDL authority, and holds exactly one reconciled
    row (A8's bootstrap-then-reconcile-then-validate ordering). Structural
    only: this function never creates, rotates, or reconciles a generation
    (A11).
    """

    cursor.execute(
        "SELECT r.rolname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_roles r ON r.oid = c.relowner WHERE n.nspname = %s AND c.relname = %s",
        (IDENTITY_SCHEMA, IDENTITY_RECOVERY_TABLE),
    )
    if cursor.fetchone() != ("emg_identity_migrator",):
        raise RuntimeError(
            "Identity recovery-state relation is absent or not owned by its migrator"
        )
    _validate_identity_table_security_state(cursor, IDENTITY_SCHEMA, IDENTITY_RECOVERY_TABLE)
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = %s::regclass AND contype = 'c'",
        (f"{IDENTITY_SCHEMA}.{IDENTITY_RECOVERY_TABLE}",),
    )
    if cursor.fetchall() != [("CHECK ((singleton_id = 1))",)]:
        raise RuntimeError("Identity recovery-state singleton constraint is missing or altered")
    cursor.execute(
        sql.SQL("SELECT count(*) FROM {}").format(
            sql.Identifier(IDENTITY_SCHEMA, IDENTITY_RECOVERY_TABLE)
        )
    )
    if cursor.fetchone() != (1,):
        raise RuntimeError("Identity recovery-state does not hold exactly one reconciled row")


def reconcile_identity_recovery(
    recovery_dsn: str,
    generation: str,
    authority_revision: str,
    *,
    live_reverify: Any = None,
) -> None:  # pragma: no cover - live PostgreSQL
    """A6: one PostgreSQL transaction that invalidates every restored
    refresh family/token, proves none remains valid, and records the
    supplied externally-authoritative (generation, authority_revision) pair.

    ``live_reverify``, when supplied, is a zero-argument callable returning
    ``(generation, authority_revision)`` from the live Approved Recovery
    Authority. It is invoked once, immediately before the recording
    statement, purely as defense-in-depth (A6): the external authority's own
    serialized rotation (A3.2) remains the primary concurrency control, and
    this re-check never substitutes for it. A mismatch aborts the
    transaction before commit.

    Crash-safe: any error before commit rolls back invalidation and the
    recovery-state write together; a crash after commit is safe because both
    are already durable; a retry with the same pair is idempotent (A6, A7(F)).
    """

    if not generation or not authority_revision:
        raise RuntimeError(
            "Identity recovery reconciliation requires a non-empty generation and revision"
        )
    _dsn_credential(recovery_dsn, "emg_identity_migrator")
    with (
        psycopg.connect(recovery_dsn) as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_user")
        if cursor.fetchone() != ("emg_identity_migrator",):
            raise RuntimeError(
                "Identity recovery reconciliation must authenticate as emg_identity_migrator"
            )
        cursor.execute(
            "SELECT r.rolname FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner "
            "WHERE n.nspname = %s",
            (IDENTITY_SCHEMA,),
        )
        if cursor.fetchone() != ("emg_identity_migrator",):
            raise RuntimeError("Identity recovery reconciliation refused: schema is not governed")
        cursor.execute(
            sql.SQL("LOCK TABLE {}, {}, {} IN SHARE ROW EXCLUSIVE MODE").format(
                sql.Identifier(IDENTITY_SCHEMA, IDENTITY_RECOVERY_TABLE),
                sql.Identifier(IDENTITY_SCHEMA, "identity_refresh_token_families"),
                sql.Identifier(IDENTITY_SCHEMA, "identity_refresh_tokens"),
            )
        )
        cursor.execute(
            sql.SQL("UPDATE {} SET revoked_at = COALESCE(revoked_at, clock_timestamp())").format(
                sql.Identifier(IDENTITY_SCHEMA, "identity_refresh_token_families")
            )
        )
        cursor.execute(
            sql.SQL("UPDATE {} SET status = 'revoked' WHERE status <> 'revoked'").format(
                sql.Identifier(IDENTITY_SCHEMA, "identity_refresh_tokens")
            )
        )
        cursor.execute(
            sql.SQL(
                "SELECT NOT EXISTS (SELECT 1 FROM {} WHERE revoked_at IS NULL) "
                "AND NOT EXISTS (SELECT 1 FROM {} WHERE status <> 'revoked')"
            ).format(
                sql.Identifier(IDENTITY_SCHEMA, "identity_refresh_token_families"),
                sql.Identifier(IDENTITY_SCHEMA, "identity_refresh_tokens"),
            )
        )
        if cursor.fetchone() != (True,):
            raise RuntimeError("Identity recovery reconciliation could not prove full invalidation")
        if live_reverify is not None:
            live_pair = live_reverify()
            if tuple(live_pair) != (generation, authority_revision):
                raise RuntimeError(
                    "Identity recovery reconciliation aborted: external authority "
                    "advanced since rotation; the supplied pair is no longer current"
                )
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (singleton_id, reconciled_generation, "
                "reconciled_authority_revision, reconciled_at) "
                "VALUES (1, %s, %s, clock_timestamp()) "
                "ON CONFLICT (singleton_id) DO UPDATE SET "
                "reconciled_generation = EXCLUDED.reconciled_generation, "
                "reconciled_authority_revision = EXCLUDED.reconciled_authority_revision, "
                "reconciled_at = EXCLUDED.reconciled_at"
            ).format(sql.Identifier(IDENTITY_SCHEMA, IDENTITY_RECOVERY_TABLE)),
            (generation, authority_revision),
        )


def validate_provisioned_databases(
    audit_migration_dsn: str,
    knowledge_graph_migration_dsn: str,
    identity_migration_dsn: str,
) -> None:  # pragma: no cover - live PostgreSQL
    _dsn_credential(audit_migration_dsn, "emg_audit_migrator")
    with psycopg.connect(audit_migration_dsn) as audit_connection:
        _validate_audit_database(audit_connection)
    with psycopg.connect(knowledge_graph_migration_dsn) as graph_connection:
        _validate_projector_database(graph_connection)
    _dsn_credential(identity_migration_dsn, "emg_identity_migrator")
    with psycopg.connect(identity_migration_dsn) as identity_connection:
        _validate_identity_database(identity_connection)
