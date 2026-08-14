"""ADR-041 Audit adoption proof against a genuinely non-superuser,
CREATEROLE PostgreSQL 16 administrator.

Every other live-PostgreSQL provisioning test in this package that exercises
Audit adoption (``test_rc1h_provisioning_integration.py``) authenticates its
"admin" DSN as ``EMG_PERSISTENCE_TEST_POSTGRES_DSN``'s superuser-equivalent
role, which owns nothing itself but is treated by PostgreSQL as having every
privilege on every object -- including implicit visibility into
``information_schema.columns``. That masked a real defect: Cloud SQL's
managed PostgreSQL 16 admin role is non-superuser (``NOSUPERUSER
CREATEROLE CREATEDB`` only) and, by this codebase's own least-privilege
design, is never granted any direct table-level privilege on
``audit_events``/``evidence_custody_events`` -- ownership and all grants
belong to ``emg_audit_migrator``/``emg_audit_app``. ``information_schema
.columns`` only lists a column when the *connecting* role owns the table or
holds some direct privilege on it, so ``_audit_schema_signature``'s defaults
read returned an empty set for a real Cloud SQL bootstrap admin regardless of
whether the table's actual defaults matched the governed contract --
rejecting every already-correctly-adopted Audit table's re-bootstrap with
"does not match the governed Audit adoption contract", even though nothing
was actually wrong with it.

This file reproduces that exact administrator shape locally (mirroring
``test_identity_bootstrap_pg16_non_superuser_admin.py``'s fixture) against a
table that was migrated by the real governed migration stream
(``run_audit_migrations``), not a hand-written approximation, and proves:
adoption succeeds when the schema is genuinely correct despite the admin
holding zero table grants (A, F); adoption still fails closed for every
class of genuine drift -- wrong default, missing default, wrong column
type, wrong nullability, and a modified constraint (B, C, D, E); the admin
gains no persistent data-plane access as a side effect of adoption (G); and
repeated bootstrap remains idempotent (H). Both governed Audit tables are
covered.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from emg_persistence.provisioning import (
    GOVERNED_DATABASE_ROLES,
    bootstrap_database_roles,
    run_audit_migrations,
)
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

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


def _role_dsns(database: str) -> dict[str, str]:
    return {
        role: _dsn(database, role, f"pg16-audit-admin-test-{role}")
        for role in GOVERNED_DATABASE_ROLES
    }


def _admin_user(admin_dsn: str) -> str:
    return str(conninfo_to_dict(admin_dsn)["user"])


@pytest.fixture
def non_superuser_admin_dsn() -> Iterator[str]:
    """A PostgreSQL 16 administrator shaped exactly like Cloud SQL's
    managed admin role: LOGIN, NOSUPERUSER, CREATEROLE, CREATEDB -- and
    nothing more. Provisioned from, and torn down by, the superuser test
    connection; never itself superuser.
    """

    assert _PG_DSN is not None
    admin_role = f"pg16_audit_admin_{uuid4().hex}"
    database = f"pg16_audit_admin_{uuid4().hex}"
    admin_password = "non-superuser-audit-admin-local-test-password"
    with psycopg.connect(_PG_DSN, autocommit=True) as connection:
        # GOVERNED_DATABASE_ROLES are fixed, cluster-global names; start from
        # a known-clean slate regardless of suite order (same rationale as
        # the Identity fixture this mirrors).
        for role in GOVERNED_DATABASE_ROLES:
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        connection.execute(
            sql.SQL("CREATE ROLE {} WITH LOGIN NOSUPERUSER CREATEROLE CREATEDB PASSWORD {}").format(
                sql.Identifier(admin_role), sql.Literal(admin_password)
            )
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(admin_role)
            )
        )
    admin_values = conninfo_to_dict(_PG_DSN)
    admin_values.update({"dbname": database, "user": admin_role, "password": admin_password})
    admin_dsn = make_conninfo(**admin_values)
    try:
        yield admin_dsn
    finally:
        with psycopg.connect(_PG_DSN, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
            for role in GOVERNED_DATABASE_ROLES:
                connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(admin_role)))


def _governed_audit_schema(admin_dsn: str) -> dict[str, str]:
    """Bring up governed roles, then apply the real Audit migration stream
    (not a hand-authored approximation) so ``audit_events``/
    ``evidence_custody_events`` exist in exactly the shape production
    Audit adoption must recognize -- owned by ``emg_audit_migrator``, with
    no grant to the bootstrap admin.
    """

    database = str(conninfo_to_dict(admin_dsn)["dbname"])
    role_dsns = _role_dsns(database)
    bootstrap_database_roles(admin_dsn, role_dsns)
    assert [m.name for m in run_audit_migrations(role_dsns["emg_audit_migrator"])] == [
        "audit_schema"
    ]
    return role_dsns


def _assert_admin_has_no_audit_table_grant(admin_dsn: str) -> None:
    admin = _admin_user(admin_dsn)
    with psycopg.connect(admin_dsn) as connection:
        for table in ("audit_events", "evidence_custody_events"):
            has_any = connection.execute(
                "SELECT has_table_privilege(%s, %s, "
                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
                (admin, table),
            ).fetchone()
            assert has_any == (False,), f"admin unexpectedly holds a grant on {table}"


@requires_postgres
def test_audit_adoption_succeeds_for_non_superuser_admin_with_no_table_grants(
    non_superuser_admin_dsn: str,
) -> None:
    """Cases A and F: the governed migration stream already produced a
    correct, migrator-owned schema; the bootstrap admin holds zero direct
    grants on either table (by design). Re-running bootstrap must adopt
    (re-validate) it successfully rather than reporting a false mismatch.

    This is the exact failure this file exists to catch: without the fix,
    this raises ``RuntimeError: existing public.audit_events does not
    match the governed Audit adoption contract`` purely because
    ``information_schema.columns`` returns nothing for a role with no
    direct grant -- not because anything about the schema is wrong.
    """

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)
    _assert_admin_has_no_audit_table_grant(non_superuser_admin_dsn)

    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        owners = connection.execute(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = current_schema() "
            "AND tablename IN ('audit_events', 'evidence_custody_events') ORDER BY tablename"
        ).fetchall()
        assert owners == [
            ("audit_events", "emg_audit_migrator"),
            ("evidence_custody_events", "emg_audit_migrator"),
        ]


@requires_postgres
def test_audit_bootstrap_admin_gains_no_persistent_privilege_after_adoption(
    non_superuser_admin_dsn: str,
) -> None:
    """Case G: adoption must not leave the bootstrap admin with standing
    data-plane access to either governed Audit table as a side effect."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)

    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)

    _assert_admin_has_no_audit_table_grant(non_superuser_admin_dsn)


@requires_postgres
def test_audit_bootstrap_is_idempotent_for_non_superuser_admin(
    non_superuser_admin_dsn: str,
) -> None:
    """Case H: repeated bootstrap against an already-adopted schema must
    keep succeeding and keep converging to the same governed state."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)

    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)
    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)
    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        owners = connection.execute(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = current_schema() "
            "AND tablename IN ('audit_events', 'evidence_custody_events') ORDER BY tablename"
        ).fetchall()
        assert owners == [
            ("audit_events", "emg_audit_migrator"),
            ("evidence_custody_events", "emg_audit_migrator"),
        ]
    _assert_admin_has_no_audit_table_grant(non_superuser_admin_dsn)


@requires_postgres
def test_audit_adoption_fails_closed_for_incorrect_default(
    non_superuser_admin_dsn: str,
) -> None:
    """Case B: a genuinely wrong default must still be rejected -- the fix
    must not have weakened this into an always-pass check."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)
    with psycopg.connect(role_dsns["emg_audit_migrator"]) as connection:
        connection.execute("ALTER TABLE audit_events ALTER COLUMN schema_version SET DEFAULT 2")

    with pytest.raises(RuntimeError, match="does not match the governed Audit adoption contract"):
        bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)


@requires_postgres
def test_audit_adoption_fails_closed_for_missing_default(
    non_superuser_admin_dsn: str,
) -> None:
    """Case C."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)
    with psycopg.connect(role_dsns["emg_audit_migrator"]) as connection:
        connection.execute("ALTER TABLE audit_events ALTER COLUMN classification DROP DEFAULT")

    with pytest.raises(RuntimeError, match="does not match the governed Audit adoption contract"):
        bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)


@requires_postgres
def test_audit_adoption_fails_closed_for_incorrect_column_type(
    non_superuser_admin_dsn: str,
) -> None:
    """Case D (type)."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)
    with psycopg.connect(role_dsns["emg_audit_migrator"]) as connection:
        connection.execute("ALTER TABLE audit_events ALTER COLUMN module TYPE varchar(64)")

    with pytest.raises(RuntimeError, match="does not match the governed Audit adoption contract"):
        bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)


@requires_postgres
def test_audit_adoption_fails_closed_for_incorrect_column_nullability(
    non_superuser_admin_dsn: str,
) -> None:
    """Case D (nullability)."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)
    with psycopg.connect(role_dsns["emg_audit_migrator"]) as connection:
        connection.execute("ALTER TABLE audit_events ALTER COLUMN resource_type SET NOT NULL")

    with pytest.raises(RuntimeError, match="does not match the governed Audit adoption contract"):
        bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)


@requires_postgres
def test_audit_adoption_fails_closed_for_incorrect_constraint(
    non_superuser_admin_dsn: str,
) -> None:
    """Case E."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)
    with psycopg.connect(role_dsns["emg_audit_migrator"]) as connection:
        connection.execute("ALTER TABLE audit_events DROP CONSTRAINT audit_events_outcome_check")
        connection.execute(
            "ALTER TABLE audit_events ADD CONSTRAINT audit_events_outcome_check "
            "CHECK (outcome = ANY (ARRAY['success'::text, 'denied'::text]))"
        )

    with pytest.raises(RuntimeError, match="does not match the governed Audit adoption contract"):
        bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)


@requires_postgres
def test_evidence_custody_events_adoption_succeeds_for_non_superuser_admin(
    non_superuser_admin_dsn: str,
) -> None:
    """Explicit coverage for the second governed Audit table: the shared
    ``_AUDIT_TABLES`` loop must adopt it too, not just ``audit_events``."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)

    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        assert connection.execute(
            "SELECT tableowner FROM pg_tables WHERE tablename = 'evidence_custody_events'"
        ).fetchone() == ("emg_audit_migrator",)


@requires_postgres
def test_evidence_custody_events_adoption_fails_closed_for_incorrect_constraint(
    non_superuser_admin_dsn: str,
) -> None:
    """Case E, second table: the fix must not have special-cased
    ``audit_events`` and silently stopped validating its sibling."""

    role_dsns = _governed_audit_schema(non_superuser_admin_dsn)
    with psycopg.connect(role_dsns["emg_audit_migrator"]) as connection:
        connection.execute(
            "ALTER TABLE evidence_custody_events "
            "DROP CONSTRAINT evidence_custody_events_custody_action_check"
        )
        connection.execute(
            "ALTER TABLE evidence_custody_events ADD CONSTRAINT "
            "evidence_custody_events_custody_action_check "
            "CHECK (custody_action = ANY (ARRAY['acquire'::text, 'transfer'::text]))"
        )

    with pytest.raises(RuntimeError, match="does not match the governed Audit adoption contract"):
        bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)
