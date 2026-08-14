"""ADR-043 Amendment 1 A4/A8 recovery-freshness gate tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from emg_identity.recovery_gate import RecoveryGateDenied, evaluate_recovery_gate

_POSTGRES_DSN = os.environ.get("EMG_IDENTITY_TEST_POSTGRES_DSN")
requires_postgres = pytest.mark.skipif(
    not _POSTGRES_DSN, reason="requires EMG_IDENTITY_TEST_POSTGRES_DSN"
)


def test_missing_authority_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RecoveryGateDenied, match="unreadable"):
        evaluate_recovery_gate(
            dsn="postgresql://unused/unused", authority_file=tmp_path / "missing.json"
        )


def test_malformed_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(RecoveryGateDenied, match="malformed"):
        evaluate_recovery_gate(dsn="postgresql://unused/unused", authority_file=path)


def test_non_object_json_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(RecoveryGateDenied, match="malformed"):
        evaluate_recovery_gate(dsn="postgresql://unused/unused", authority_file=path)


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '{"generation": "gen-1"}',
        '{"authority_revision": "1"}',
        '{"generation": "", "authority_revision": "1"}',
        '{"generation": "gen-1", "authority_revision": ""}',
        '{"generation": 1, "authority_revision": "1"}',
    ],
)
def test_missing_or_blank_or_wrong_type_field_fails_closed(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "authority.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(RecoveryGateDenied, match="missing a required field"):
        evaluate_recovery_gate(dsn="postgresql://unused/unused", authority_file=path)


@requires_postgres
def test_database_unavailable_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    path.write_text('{"generation": "gen-1", "authority_revision": "1"}', encoding="utf-8")
    with pytest.raises(RecoveryGateDenied, match="recovery state unavailable"):
        evaluate_recovery_gate(
            dsn="postgresql://nonexistent-host-for-test:1/nope",
            authority_file=path,
            timeout_seconds=1,
        )


@requires_postgres
def test_missing_recovery_row_fails_closed(tmp_path: Path) -> None:
    from uuid import uuid4

    import psycopg
    from emg_persistence.provisioning import bootstrap_database_roles, run_identity_migrations
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    assert _POSTGRES_DSN is not None
    database = f"gate_{uuid4().hex}"
    values = conninfo_to_dict(_POSTGRES_DSN)
    values["dbname"] = database
    admin_dsn = make_conninfo(**values)
    with psycopg.connect(_POSTGRES_DSN, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:

        def dsn(user: str, password: str) -> str:
            v = dict(values)
            v.update({"user": user, "password": password})
            return make_conninfo(**v)

        role_dsns = {
            "emg_audit_migrator": dsn("emg_audit_migrator", "p"),
            "emg_audit_app": dsn("emg_audit_app", "p"),
            "emg_audit_projector": dsn("emg_audit_projector", "p"),
            "emg_knowledge_graph_migrator": dsn("emg_knowledge_graph_migrator", "p"),
            "emg_knowledge_graph_app": dsn("emg_knowledge_graph_app", "p"),
            "emg_identity_migrator": dsn("emg_identity_migrator", "p"),
            "emg_identity_app": dsn("emg_identity_app", "p"),
        }
        bootstrap_database_roles(admin_dsn, role_dsns)
        run_identity_migrations(role_dsns["emg_identity_migrator"])

        path = tmp_path / "authority.json"
        path.write_text('{"generation": "gen-1", "authority_revision": "1"}', encoding="utf-8")
        with pytest.raises(RecoveryGateDenied, match="missing or duplicated"):
            evaluate_recovery_gate(dsn=role_dsns["emg_identity_app"], authority_file=path)
    finally:
        with psycopg.connect(_POSTGRES_DSN, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


@requires_postgres
def test_matching_and_mismatched_pair(tmp_path: Path) -> None:
    from uuid import uuid4

    import psycopg
    from emg_persistence.provisioning import (
        InMemoryApprovedRecoveryAuthority,
        bootstrap_database_roles,
        reconcile_identity_recovery,
        run_identity_migrations,
    )
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    assert _POSTGRES_DSN is not None
    database = f"gate_{uuid4().hex}"
    values = conninfo_to_dict(_POSTGRES_DSN)
    values["dbname"] = database
    admin_dsn = make_conninfo(**values)
    with psycopg.connect(_POSTGRES_DSN, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:

        def dsn(user: str, password: str) -> str:
            v = dict(values)
            v.update({"user": user, "password": password})
            return make_conninfo(**v)

        role_dsns = {
            "emg_audit_migrator": dsn("emg_audit_migrator", "p"),
            "emg_audit_app": dsn("emg_audit_app", "p"),
            "emg_audit_projector": dsn("emg_audit_projector", "p"),
            "emg_knowledge_graph_migrator": dsn("emg_knowledge_graph_migrator", "p"),
            "emg_knowledge_graph_app": dsn("emg_knowledge_graph_app", "p"),
            "emg_identity_migrator": dsn("emg_identity_migrator", "p"),
            "emg_identity_app": dsn("emg_identity_app", "p"),
        }
        bootstrap_database_roles(admin_dsn, role_dsns)
        run_identity_migrations(role_dsns["emg_identity_migrator"])
        pair = InMemoryApprovedRecoveryAuthority().read_current()
        reconcile_identity_recovery(
            role_dsns["emg_identity_migrator"], pair.generation, pair.authority_revision
        )

        matching = tmp_path / "matching.json"
        matching.write_text(
            f'{{"generation": "{pair.generation}", '
            f'"authority_revision": "{pair.authority_revision}"}}',
            encoding="utf-8",
        )
        # no raise:
        evaluate_recovery_gate(dsn=role_dsns["emg_identity_app"], authority_file=matching)

        mismatched = tmp_path / "mismatched.json"
        mismatched.write_text(
            '{"generation": "some-other-generation", "authority_revision": "99"}',
            encoding="utf-8",
        )
        with pytest.raises(RecoveryGateDenied, match="does not match"):
            evaluate_recovery_gate(dsn=role_dsns["emg_identity_app"], authority_file=mismatched)
    finally:
        with psycopg.connect(_POSTGRES_DSN, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
