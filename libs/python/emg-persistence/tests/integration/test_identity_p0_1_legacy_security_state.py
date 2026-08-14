"""ADR-043 P0-1 adversarial legacy-adoption and Stage-50 security-state tests.

Each test deliberately introduces one security-material catalog divergence
(ACL, column ACL, PUBLIC, ownership, trigger, RLS, FORCE RLS, policy, rule,
security label, migration-history exposure, role membership, cross-schema
authority, or unauthorized runtime column UPDATE) and proves adoption or
Stage-50 validation fails closed rather than silently normalizing it (D-6,
A11). A clean legacy-adoption success path is already proven by
``test_identity_exact_legacy_adoption_preserves_rows_and_rejects_divergence``
in ``test_rc1h_provisioning_integration.py``; this file only adds the
divergence cases.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from emg_persistence.provisioning import bootstrap_database_roles
from emg_persistence.provisioning.database import _validate_identity_database
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_PG_DSN = os.environ.get("EMG_PERSISTENCE_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _PG_DSN, reason="requires EMG_PERSISTENCE_TEST_POSTGRES_DSN"
)


def _dsn(database: str, user: str, password: str) -> str:
    assert _PG_DSN is not None
    values = conninfo_to_dict(_PG_DSN)
    values.update({"dbname": database, "user": user, "password": password})
    return make_conninfo(**values)


def _bootstrap_role_dsns(admin_dsn: str) -> dict[str, str]:
    database = str(conninfo_to_dict(admin_dsn)["dbname"])
    return {
        "emg_audit_migrator": _dsn(database, "emg_audit_migrator", "p0-1-audit-migrator"),
        "emg_audit_app": _dsn(database, "emg_audit_app", "p0-1-audit-app"),
        "emg_audit_projector": _dsn(database, "emg_audit_projector", "p0-1-audit-projector"),
        "emg_knowledge_graph_migrator": _dsn(
            database, "emg_knowledge_graph_migrator", "p0-1-kg-migrator"
        ),
        "emg_knowledge_graph_app": _dsn(database, "emg_knowledge_graph_app", "p0-1-kg-app"),
        "emg_identity_migrator": _dsn(database, "emg_identity_migrator", "p0-1-identity-migrator"),
        "emg_identity_app": _dsn(database, "emg_identity_app", "p0-1-identity-app"),
    }


@pytest.fixture
def admin_dsn() -> Iterator[str]:
    assert _PG_DSN is not None
    database = f"p0_1_{uuid4().hex}"
    values = conninfo_to_dict(_PG_DSN)
    values["dbname"] = database
    dsn = make_conninfo(**values)
    with psycopg.connect(_PG_DSN, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        yield dsn
    finally:
        with psycopg.connect(_PG_DSN, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def _create_clean_legacy_tables(connection: psycopg.Connection) -> None:
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


_ENSURE_THIRD_PARTY_ROLE = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
    "'p0_1_third_party') THEN CREATE ROLE p0_1_third_party LOGIN; END IF; END $$; "
)
_ENSURE_IDENTITY_APP_ROLE = (
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
    "'emg_identity_app') THEN CREATE ROLE emg_identity_app LOGIN; END IF; END $$; "
)
_DIVERGENCE_CASES: dict[str, tuple[str, str]] = {
    "third_party_select_grant": (
        _ENSURE_THIRD_PARTY_ROLE
        + "GRANT SELECT ON identity_refresh_token_families TO p0_1_third_party",
        "unexpected table-level grantee",
    ),
    "third_party_insert_update_grant": (
        _ENSURE_THIRD_PARTY_ROLE
        + "GRANT INSERT, UPDATE ON identity_refresh_token_families TO p0_1_third_party",
        "unexpected table-level grantee",
    ),
    "unexpected_column_acl": (
        _ENSURE_IDENTITY_APP_ROLE
        + "GRANT UPDATE (created_at) ON identity_refresh_token_families TO emg_identity_app",
        "unexpected column-level grantee",
    ),
    "public_grant": (
        "GRANT SELECT ON identity_refresh_token_families TO PUBLIC",
        "unexpected table-level grantee",
    ),
    "user_defined_trigger": (
        "CREATE FUNCTION p0_1_noop() RETURNS trigger AS $$ BEGIN RETURN NEW; END; $$ "
        "LANGUAGE plpgsql; "
        "CREATE TRIGGER p0_1_trigger BEFORE INSERT ON identity_refresh_token_families "
        "FOR EACH ROW EXECUTE FUNCTION p0_1_noop()",
        "unexpected user-defined trigger",
    ),
    "rls_enabled": (
        "ALTER TABLE identity_refresh_token_families ENABLE ROW LEVEL SECURITY",
        "unexpected row-level security state",
    ),
    "force_rls": (
        "ALTER TABLE identity_refresh_token_families ENABLE ROW LEVEL SECURITY; "
        "ALTER TABLE identity_refresh_token_families FORCE ROW LEVEL SECURITY",
        "unexpected row-level security state",
    ),
    "policy": (
        "ALTER TABLE identity_refresh_token_families ENABLE ROW LEVEL SECURITY; "
        "CREATE POLICY p0_1_policy ON identity_refresh_token_families USING (true)",
        # RLS-enabled state is detected before the policy-specific check runs;
        # both are catalog-divergence rejections, proving fail-closed either way.
        "unexpected row-level security state",
    ),
    "rule": (
        "CREATE RULE p0_1_rule AS ON UPDATE TO identity_refresh_token_families DO NOTHING",
        "unexpected rule",
    ),
}


@requires_postgres
@pytest.mark.parametrize("case", sorted(_DIVERGENCE_CASES))
def test_identity_legacy_adoption_rejects_each_security_divergence(
    admin_dsn: str, case: str
) -> None:  # pragma: no cover
    setup_sql, expected_message = _DIVERGENCE_CASES[case]
    role_dsns = _bootstrap_role_dsns(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        _create_clean_legacy_tables(connection)
        connection.execute(setup_sql)

    with pytest.raises(RuntimeError, match=expected_message):
        bootstrap_database_roles(admin_dsn, role_dsns)

    with psycopg.connect(admin_dsn) as connection:
        # Adoption must not have proceeded: the table must remain in public,
        # un-adopted, with the divergent state undisturbed (fail closed, not
        # silently normalized).
        assert connection.execute(
            "SELECT to_regclass('public.identity_refresh_token_families') IS NOT NULL"
        ).fetchone() == (True,)
        assert connection.execute(
            "SELECT to_regclass('emg_identity.identity_refresh_token_families')"
        ).fetchone() == (None,)


@requires_postgres
def test_identity_legacy_adoption_rejects_security_label_when_supported(
    admin_dsn: str,
) -> None:  # pragma: no cover
    role_dsns = _bootstrap_role_dsns(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        _create_clean_legacy_tables(connection)
        try:
            connection.execute(
                "SECURITY LABEL ON TABLE identity_refresh_token_families IS 'p0_1_test_label'"
            )
        except psycopg.errors.InvalidParameterValue:
            pytest.skip("no security label provider is loaded in this test environment")

    with pytest.raises(RuntimeError, match="unexpected security label"):
        bootstrap_database_roles(admin_dsn, role_dsns)


@requires_postgres
def test_identity_legacy_adoption_clean_grant_baseline_still_succeeds(
    admin_dsn: str,
) -> None:  # pragma: no cover
    """Positive control: legacy grants that already exactly equal the
    governed baseline (as the historical local seed script established) are
    accepted, proving the divergence tests above fail for the right reason
    and not merely because any grant at all is present."""

    role_dsns = _bootstrap_role_dsns(admin_dsn)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        _create_clean_legacy_tables(connection)
        connection.execute(_ENSURE_IDENTITY_APP_ROLE)
        connection.execute(
            "GRANT SELECT, INSERT ON identity_refresh_token_families, "
            "identity_refresh_tokens TO emg_identity_app"
        )
        connection.execute(
            "GRANT UPDATE (revoked_at) ON identity_refresh_token_families TO emg_identity_app"
        )
        connection.execute(
            "GRANT UPDATE (status, rotated_at) ON identity_refresh_tokens TO emg_identity_app"
        )

    bootstrap_database_roles(admin_dsn, role_dsns)

    with psycopg.connect(role_dsns["emg_identity_migrator"]) as connection:
        assert connection.execute(
            "SELECT to_regclass('emg_identity.identity_refresh_token_families') IS NOT NULL"
        ).fetchone() == (True,)


@requires_postgres
def test_identity_stage50_rejects_migration_history_exposure(
    admin_dsn: str,
) -> None:  # pragma: no cover
    from emg_persistence.provisioning import reconcile_identity_recovery, run_identity_migrations
    from emg_persistence.provisioning.recovery_authority import InMemoryApprovedRecoveryAuthority

    role_dsns = _bootstrap_role_dsns(admin_dsn)
    bootstrap_database_roles(admin_dsn, role_dsns)
    migrator_dsn = role_dsns["emg_identity_migrator"]
    run_identity_migrations(migrator_dsn)
    pair = InMemoryApprovedRecoveryAuthority().read_current()
    reconcile_identity_recovery(migrator_dsn, pair.generation, pair.authority_revision)

    with psycopg.connect(migrator_dsn) as connection:
        _validate_identity_database(connection)  # baseline: passes before the divergence
        connection.execute(
            "GRANT SELECT ON emg_identity.identity_schema_migrations TO emg_identity_app"
        )
        with pytest.raises(RuntimeError, match="privileges do not match ADR-043"):
            _validate_identity_database(connection)
        connection.rollback()


@requires_postgres
def test_identity_stage50_rejects_role_membership_broadening_authority(
    admin_dsn: str,
) -> None:  # pragma: no cover
    from emg_persistence.provisioning import reconcile_identity_recovery, run_identity_migrations
    from emg_persistence.provisioning.recovery_authority import InMemoryApprovedRecoveryAuthority

    role_dsns = _bootstrap_role_dsns(admin_dsn)
    bootstrap_database_roles(admin_dsn, role_dsns)
    migrator_dsn = role_dsns["emg_identity_migrator"]
    run_identity_migrations(migrator_dsn)
    pair = InMemoryApprovedRecoveryAuthority().read_current()
    reconcile_identity_recovery(migrator_dsn, pair.generation, pair.authority_revision)

    with psycopg.connect(admin_dsn) as connection:
        connection.execute("GRANT emg_identity_migrator TO emg_identity_app")
    try:
        with (
            psycopg.connect(migrator_dsn) as connection,
            pytest.raises(RuntimeError, match="prohibited role membership"),
        ):
            _validate_identity_database(connection)
    finally:
        # Role membership is cluster-global, not per-database; revoke it so
        # this test does not contaminate other tests reusing the same
        # governed role names against a fresh database.
        with psycopg.connect(admin_dsn) as connection:
            connection.execute("REVOKE emg_identity_migrator FROM emg_identity_app")


@requires_postgres
def test_identity_stage50_rejects_unauthorized_runtime_column_update(
    admin_dsn: str,
) -> None:  # pragma: no cover
    from emg_persistence.provisioning import reconcile_identity_recovery, run_identity_migrations
    from emg_persistence.provisioning.recovery_authority import InMemoryApprovedRecoveryAuthority

    role_dsns = _bootstrap_role_dsns(admin_dsn)
    bootstrap_database_roles(admin_dsn, role_dsns)
    migrator_dsn = role_dsns["emg_identity_migrator"]
    run_identity_migrations(migrator_dsn)
    pair = InMemoryApprovedRecoveryAuthority().read_current()
    reconcile_identity_recovery(migrator_dsn, pair.generation, pair.authority_revision)

    with psycopg.connect(migrator_dsn) as connection:
        connection.execute(
            "GRANT UPDATE (expires_at) ON emg_identity.identity_refresh_tokens "
            "TO emg_identity_app"
        )
        with pytest.raises(RuntimeError, match="unexpected column-level grantee"):
            _validate_identity_database(connection)
        connection.rollback()


@requires_postgres
def test_identity_recovery_state_stage50_rejects_mutation_grant(
    admin_dsn: str,
) -> None:  # pragma: no cover
    from emg_persistence.provisioning import reconcile_identity_recovery, run_identity_migrations
    from emg_persistence.provisioning.recovery_authority import InMemoryApprovedRecoveryAuthority

    role_dsns = _bootstrap_role_dsns(admin_dsn)
    bootstrap_database_roles(admin_dsn, role_dsns)
    migrator_dsn = role_dsns["emg_identity_migrator"]
    run_identity_migrations(migrator_dsn)
    pair = InMemoryApprovedRecoveryAuthority().read_current()
    reconcile_identity_recovery(migrator_dsn, pair.generation, pair.authority_revision)

    with psycopg.connect(migrator_dsn) as connection:
        _validate_identity_database(connection)
        connection.execute(
            "GRANT INSERT ON emg_identity.identity_recovery_state TO emg_identity_app"
        )
        with pytest.raises(RuntimeError, match="unexpected table-level grantee"):
            _validate_identity_database(connection)
        connection.rollback()
