"""ADR-043 / ADR-041 bootstrap proof against a genuinely non-superuser,
CREATEROLE PostgreSQL 16 administrator.

Every other live-PostgreSQL provisioning test in this package authenticates
``EMG_PERSISTENCE_TEST_POSTGRES_DSN`` as a superuser-equivalent local
trust-auth role, which bypasses PostgreSQL's role-membership privilege
checks entirely. That masked a real defect: Cloud SQL's managed PostgreSQL
16 admin role is non-superuser with only CREATEROLE, and PostgreSQL 16
grants such an administrator only ADMIN OPTION (management rights) over a
role it creates -- never INHERIT or SET (the rights required to act with
that role's own privileges). ``CREATE SCHEMA ... AUTHORIZATION
emg_identity_migrator`` and ``ALTER TABLE ... OWNER TO emg_identity_migrator``
both require the latter, so bootstrap failed in any real non-superuser
environment (staging and production Cloud SQL alike) while passing every
existing test.

This file reproduces that exact administrator shape locally and proves:
bootstrap now succeeds, is idempotent, converges the legacy-adoption path
too, does not weaken audit/knowledge_graph bootstrap, and does not leave
the administrator with standing usage-level (SET ROLE) access to the
Identity role it manages.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from emg_persistence.provisioning import GOVERNED_DATABASE_ROLES, bootstrap_database_roles
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.errors import InsufficientPrivilege

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)


def _dsn(database: str, user: str, password: str) -> str:
    assert _PG_DSN is not None
    values = conninfo_to_dict(_PG_DSN)
    values.update({"dbname": database, "user": user, "password": password})
    return make_conninfo(**values)


def _role_dsns(database: str) -> dict[str, str]:
    return {
        role: _dsn(database, role, f"pg16-admin-test-{role}") for role in GOVERNED_DATABASE_ROLES
    }


@pytest.fixture
def non_superuser_admin_dsn() -> Iterator[str]:
    """A PostgreSQL 16 administrator shaped exactly like Cloud SQL's
    managed admin role: LOGIN, NOSUPERUSER, CREATEROLE, CREATEDB -- and
    nothing more. Provisioned from, and torn down by, the superuser test
    connection; never itself superuser.
    """

    assert _PG_DSN is not None
    admin_role = f"pg16_admin_{uuid4().hex}"
    database = f"pg16_admin_{uuid4().hex}"
    admin_password = "non-superuser-admin-local-test-password"
    with psycopg.connect(_PG_DSN, autocommit=True) as connection:
        # GOVERNED_DATABASE_ROLES are fixed, cluster-global names. Other
        # test files' fixtures create them under the superuser test
        # connection and never drop them (harmless for those tests, which
        # always reuse that same superuser admin). This fixture's admin is
        # a different, non-superuser role each run, so it must not inherit
        # ADMIN OPTION from whichever admin created a role in an earlier
        # test -- start from a known-clean slate regardless of suite order.
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
            # GOVERNED_DATABASE_ROLES are fixed, cluster-global names (roles
            # are not database-scoped in PostgreSQL): drop them so the next
            # test's freshly-minted, differently-named admin role does not
            # collide with roles a prior test's admin created and holds
            # ADMIN OPTION over.
            for role in GOVERNED_DATABASE_ROLES:
                connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(admin_role)))


def _admin_user(admin_dsn: str) -> str:
    return str(conninfo_to_dict(admin_dsn)["user"])


@requires_postgres
def test_bootstrap_succeeds_for_non_superuser_createrole_admin(
    non_superuser_admin_dsn: str,
) -> None:
    """This is the exact failure this file exists to catch: without the
    fix, this raises ``psycopg.errors.InsufficientPrivilege: must be able
    to SET ROLE "emg_identity_migrator"``. Manually confirmed (git stash)
    to fail on the pre-fix implementation and pass here."""

    database = str(conninfo_to_dict(non_superuser_admin_dsn)["dbname"])
    bootstrap_database_roles(non_superuser_admin_dsn, _role_dsns(database))

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        owner = connection.execute(
            "SELECT r.rolname FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner "
            "WHERE n.nspname = 'emg_identity'"
        ).fetchone()
        assert owner == ("emg_identity_migrator",)


@requires_postgres
def test_bootstrap_is_idempotent_for_non_superuser_admin(non_superuser_admin_dsn: str) -> None:
    database = str(conninfo_to_dict(non_superuser_admin_dsn)["dbname"])
    role_dsns = _role_dsns(database)

    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)
    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)
    bootstrap_database_roles(non_superuser_admin_dsn, role_dsns)

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        rows = connection.execute(
            "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
            "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
            (list(GOVERNED_DATABASE_ROLES),),
        ).fetchall()
        assert len(rows) == len(GOVERNED_DATABASE_ROLES)
        for row in rows:
            assert tuple(bool(value) for value in row[1:]) == (
                True,
                False,
                False,
                False,
                False,
                False,
                False,
            ), f"role {row[0]} is non-conformant after repeated bootstrap"


@requires_postgres
def test_identity_schema_privileges_are_correct_after_bootstrap(
    non_superuser_admin_dsn: str,
) -> None:
    database = str(conninfo_to_dict(non_superuser_admin_dsn)["dbname"])
    bootstrap_database_roles(non_superuser_admin_dsn, _role_dsns(database))

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        public_usage, public_create, app_create = connection.execute(
            "SELECT has_schema_privilege('public', 'emg_identity', 'USAGE'), "
            "has_schema_privilege('public', 'emg_identity', 'CREATE'), "
            "has_schema_privilege('emg_identity_app', 'emg_identity', 'CREATE')"
        ).fetchone()
        assert (public_usage, public_create, app_create) == (False, False, False)


@requires_postgres
def test_admin_retains_no_set_role_privilege_after_bootstrap(
    non_superuser_admin_dsn: str,
) -> None:
    """The core privilege-boundary assertion: a temporary grant was
    necessary to author the schema/table, but the administrator must not
    retain standing membership sufficient to act as emg_identity_migrator
    once bootstrap completes (requirement: no unintended residual
    membership)."""

    database = str(conninfo_to_dict(non_superuser_admin_dsn)["dbname"])
    bootstrap_database_roles(non_superuser_admin_dsn, _role_dsns(database))

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        usage = connection.execute(
            "SELECT has_schema_privilege(%s, 'emg_identity', 'USAGE')",
            (_admin_user(non_superuser_admin_dsn),),
        ).fetchone()
        assert usage == (False,)
        with pytest.raises(InsufficientPrivilege, match="permission denied to set role"):
            connection.execute("SET ROLE emg_identity_migrator")


@requires_postgres
def test_admin_retains_administrative_membership_for_future_reconvergence(
    non_superuser_admin_dsn: str,
) -> None:
    """The administrator's ADMIN OPTION membership over roles it created
    is PostgreSQL's own automatic, structural side effect of CREATE ROLE
    under CREATEROLE -- not something this fix introduces or removes -- and
    it is load-bearing: ``_create_or_converge_role`` must be able to ALTER
    the role on every future bootstrap run. This is the deliberate
    counterpart to the previous test: administration rights persist,
    usage rights do not."""

    database = str(conninfo_to_dict(non_superuser_admin_dsn)["dbname"])
    bootstrap_database_roles(non_superuser_admin_dsn, _role_dsns(database))

    with psycopg.connect(non_superuser_admin_dsn, autocommit=True) as connection:
        connection.execute("ALTER ROLE emg_identity_migrator PASSWORD 'reconverged-password'")
        admin_option = connection.execute(
            "SELECT am.admin_option FROM pg_auth_members am "
            "JOIN pg_roles r ON r.oid = am.roleid JOIN pg_roles m ON m.oid = am.member "
            "WHERE r.rolname = 'emg_identity_migrator' AND m.rolname = %s",
            (_admin_user(non_superuser_admin_dsn),),
        ).fetchone()
        assert admin_option == (True,)


@requires_postgres
def test_legacy_identity_schema_adoption_succeeds_for_non_superuser_admin(
    non_superuser_admin_dsn: str,
) -> None:
    """``_adopt_existing_identity_schema``'s legacy-table path does
    ``ALTER TABLE ... OWNER TO emg_identity_migrator``, which has the
    identical PostgreSQL 16 SET ROLE requirement as schema creation."""

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        connection.execute(
            "CREATE TABLE identity_refresh_token_families ("
            "family_hash TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL "
            "DEFAULT clock_timestamp(), revoked_at TIMESTAMPTZ)"
        )
        connection.execute(
            "CREATE TABLE identity_refresh_tokens (token_hash TEXT PRIMARY KEY, "
            "family_hash TEXT NOT NULL REFERENCES "
            "identity_refresh_token_families(family_hash), "
            "status TEXT NOT NULL CHECK (status IN ('active', 'rotated', 'revoked')), "
            "expires_at TIMESTAMPTZ NOT NULL, rotated_at TIMESTAMPTZ)"
        )
        connection.execute(
            "CREATE INDEX idx_identity_refresh_tokens_family "
            "ON identity_refresh_tokens (family_hash)"
        )

    database = str(conninfo_to_dict(non_superuser_admin_dsn)["dbname"])
    bootstrap_database_roles(non_superuser_admin_dsn, _role_dsns(database))

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        owners = connection.execute(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'emg_identity' "
            "ORDER BY tablename"
        ).fetchall()
        assert {row[1] for row in owners} == {"emg_identity_migrator"}
        assert {row[0] for row in owners} == {
            "identity_refresh_token_families",
            "identity_refresh_tokens",
        }
        remaining_in_public = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename LIKE 'identity_refresh%'"
        ).fetchall()
        assert remaining_in_public == []
        usage = connection.execute(
            "SELECT has_schema_privilege(%s, 'emg_identity', 'USAGE')",
            (_admin_user(non_superuser_admin_dsn),),
        ).fetchone()
        assert usage == (False,)


@requires_postgres
def test_audit_and_knowledge_graph_bootstrap_unaffected_for_non_superuser_admin(
    non_superuser_admin_dsn: str,
) -> None:
    """Regression guard: audit/knowledge_graph role and schema-grant
    bootstrap never needed SET ROLE (it only GRANTs privileges TO the
    role, never authors an object AUTHORIZATION'd to it) and must keep
    working unchanged for the same non-superuser administrator."""

    database = str(conninfo_to_dict(non_superuser_admin_dsn)["dbname"])
    bootstrap_database_roles(non_superuser_admin_dsn, _role_dsns(database))

    with psycopg.connect(non_superuser_admin_dsn) as connection:
        audit_usage, audit_create, kg_usage, kg_create, app_create = connection.execute(
            "SELECT has_schema_privilege('emg_audit_migrator', 'public', 'USAGE'), "
            "has_schema_privilege('emg_audit_migrator', 'public', 'CREATE'), "
            "has_schema_privilege('emg_knowledge_graph_migrator', 'public', 'USAGE'), "
            "has_schema_privilege('emg_knowledge_graph_migrator', 'public', 'CREATE'), "
            "has_schema_privilege('emg_audit_app', 'public', 'CREATE')"
        ).fetchone()
        assert (audit_usage, audit_create, kg_usage, kg_create, app_create) == (
            True,
            True,
            True,
            True,
            False,
        )
