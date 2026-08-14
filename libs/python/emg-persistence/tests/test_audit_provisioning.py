from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from emg_persistence.migrate import audit_migrations_dir, identity_migrations_dir
from emg_persistence.provisioning import (
    AUDIT_HISTORY_TABLE,
    GOVERNED_DATABASE_ROLES,
    IDENTITY_HISTORY_RELATION,
)
from emg_persistence.provisioning import __main__ as provisioning_cli
from emg_persistence.provisioning.database import _create_or_converge_role


class _RoleCursor:
    def __init__(self, attributes: tuple[bool, ...] | None, *, ignore_mutable_alter: bool = False):
        self.attributes = attributes
        self.ignore_mutable_alter = ignore_mutable_alter
        self.statements: list[str] = []
        self.password_updates = 0

    def execute(self, query: Any, _params: Any = None) -> None:
        statement = query if isinstance(query, str) else query.as_string(None)
        self.statements.append(statement)
        if statement.startswith("CREATE ROLE"):
            self.attributes = (True, False, False, False, False, False, False)
        elif statement.startswith("ALTER ROLE") and " WITH LOGIN" in statement:
            assert "NOSUPERUSER" not in statement
            assert "NOREPLICATION" not in statement
            assert "NOBYPASSRLS" not in statement
            if not self.ignore_mutable_alter and self.attributes is not None:
                self.attributes = (
                    True,
                    self.attributes[1],
                    False,
                    False,
                    False,
                    self.attributes[5],
                    self.attributes[6],
                )
        elif statement.startswith("ALTER ROLE") and " PASSWORD " in statement:
            self.password_updates += 1

    def fetchone(self) -> tuple[bool, ...] | None:
        return self.attributes


def test_database_bootstrap_declares_only_adr_041_roles() -> None:
    assert GOVERNED_DATABASE_ROLES == (
        "emg_audit_migrator",
        "emg_audit_app",
        "emg_audit_projector",
        "emg_knowledge_graph_migrator",
        "emg_knowledge_graph_app",
        "emg_identity_migrator",
        "emg_identity_app",
    )
    assert AUDIT_HISTORY_TABLE == "audit_schema_migrations"
    assert IDENTITY_HISTORY_RELATION == "emg_identity.identity_schema_migrations"


def test_identity_migration_is_the_only_refresh_schema_authority() -> None:
    sql = (identity_migrations_dir() / "V001__identity_refresh_state.sql").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(sql.split())
    seed = Path("tools/seed-data/postgres/007_identity_refresh_tokens.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE IF NOT EXISTS emg_identity.identity_refresh_token_families" in normalized
    assert "CREATE TABLE IF NOT EXISTS emg_identity.identity_refresh_tokens" in normalized
    assert "GRANT UPDATE (revoked_at)" in normalized
    assert "GRANT UPDATE (status, rotated_at)" in normalized
    assert "REVOKE DELETE, TRUNCATE" in normalized
    assert "REVOKE ALL ON emg_identity.identity_schema_migrations" in normalized
    assert "CREATE ROLE" not in normalized and "PASSWORD" not in normalized
    assert "CREATE TABLE" not in seed and "CREATE INDEX" not in seed


def test_audit_migration_preserves_seed_semantics_and_runtime_restriction() -> None:
    sql = (audit_migrations_dir() / "V001__audit_schema.sql").read_text(encoding="utf-8")
    normalized = " ".join(sql.split())

    assert "CREATE TABLE IF NOT EXISTS audit_events" in normalized
    assert "CREATE TABLE IF NOT EXISTS evidence_custody_events" in normalized
    assert "PRIMARY KEY (source_principal, event_id)" in normalized
    assert "UNIQUE (evidence_id, custody_sequence)" in normalized
    assert "tenant_id TEXT NOT NULL DEFAULT 'legacy-unscoped'" in normalized
    assert "ALTER TABLE audit_events OWNER TO emg_audit_migrator" in normalized
    assert "ALTER TABLE evidence_custody_events OWNER TO emg_audit_migrator" in normalized
    assert (
        "GRANT INSERT, SELECT ON audit_events, evidence_custody_events TO emg_audit_app"
        in normalized
    )
    assert "REVOKE CREATE ON SCHEMA public FROM emg_audit_app" in normalized
    assert "DROP TABLE" not in normalized
    assert "TRUNCATE audit_events" not in normalized
    assert "CREATE ROLE" not in normalized
    assert "PASSWORD" not in normalized


def test_production_audit_migration_stream_does_not_reference_local_seed_sql() -> None:
    for path in audit_migrations_dir().glob("*.sql"):
        sql = path.read_text(encoding="utf-8")
        assert "tools/seed-data" not in sql
        assert "local_dev" not in sql


def test_database_bootstrap_cli_sources_all_role_credentials_from_canonical_dsns(
    monkeypatch,
) -> None:
    env = {
        "EMG_DATABASE_BOOTSTRAP_ADMIN_DSN": "admin-dsn",
        "EMG_AUDIT_MIGRATION_POSTGRES_DSN": "audit-migration-dsn",
        "EMG_AUDIT_POSTGRES_DSN": "audit-runtime-dsn",
        "EMG_AUDIT_PROJECTOR_POSTGRES_DSN": "audit-projector-dsn",
        "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN": "kg-migration-dsn",
        "EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN": "kg-runtime-dsn",
        "EMG_IDENTITY_MIGRATION_POSTGRES_DSN": "identity-migration-dsn",
        "EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN": "identity-runtime-dsn",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    calls: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(
        provisioning_cli,
        "bootstrap_database_roles",
        lambda admin_dsn, role_dsns: calls.append((admin_dsn, dict(role_dsns))),
    )
    monkeypatch.setattr(sys, "argv", ["emg-persistence-provisioning", "database-bootstrap"])

    provisioning_cli.main()

    assert calls == [
        (
            "admin-dsn",
            {
                "emg_audit_migrator": "audit-migration-dsn",
                "emg_audit_app": "audit-runtime-dsn",
                "emg_audit_projector": "audit-projector-dsn",
                "emg_knowledge_graph_migrator": "kg-migration-dsn",
                "emg_knowledge_graph_app": "kg-runtime-dsn",
                "emg_identity_migrator": "identity-migration-dsn",
                "emg_identity_app": "identity-runtime-dsn",
            },
        )
    ]


def test_role_creation_uses_explicit_complete_safe_attributes() -> None:
    cursor = _RoleCursor(None)

    _create_or_converge_role(cursor, "emg_audit_app", "synthetic-password")

    create = next(statement for statement in cursor.statements if statement.startswith("CREATE"))
    assert (
        "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT " "NOREPLICATION NOBYPASSRLS"
    ) in create
    assert cursor.password_updates == 1


def test_existing_safe_role_converges_without_reserved_cloud_sql_alter_clauses() -> None:
    cursor = _RoleCursor((False, False, True, True, True, False, False))

    _create_or_converge_role(cursor, "emg_audit_app", "rotated-synthetic-password")

    convergence = next(
        statement
        for statement in cursor.statements
        if statement.startswith("ALTER ROLE") and " WITH LOGIN" in statement
    )
    assert convergence.endswith("WITH LOGIN NOCREATEDB NOCREATEROLE NOINHERIT")
    assert cursor.attributes == (True, False, False, False, False, False, False)
    assert cursor.password_updates == 1


@pytest.mark.parametrize("unsafe_index", (1, 5, 6))
def test_existing_role_with_reserved_privilege_fails_before_alter(unsafe_index: int) -> None:
    attributes = [True, False, False, False, False, False, False]
    attributes[unsafe_index] = True
    cursor = _RoleCursor(tuple(attributes))

    with pytest.raises(RuntimeError, match="privileged attributes"):
        _create_or_converge_role(cursor, "emg_audit_app", "synthetic-password")

    assert not [statement for statement in cursor.statements if statement.startswith("ALTER ROLE")]


@pytest.mark.parametrize("unsafe_index", (2, 3, 4))
def test_role_fails_closed_if_mutable_attribute_cannot_be_converged(unsafe_index: int) -> None:
    attributes = [True, False, False, False, False, False, False]
    attributes[unsafe_index] = True
    cursor = _RoleCursor(tuple(attributes), ignore_mutable_alter=True)

    with pytest.raises(RuntimeError, match="non-conformant attributes"):
        _create_or_converge_role(cursor, "emg_audit_app", "synthetic-password")
