"""ADR-043 Amendment 1 A9.3 database-session fence: real-PostgreSQL proof.

Round-2 remediation: the original review found A9.3 "prose-only" -- no
executable, checkable positive-evidence mechanism existed. This test proves
the real mechanism against a real PostgreSQL instance: a genuine surviving
`emg_identity_app` session is detected, terminated, and re-proven absent
before evidence is written, and evidence is never written on failure.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from emg_persistence.provisioning import (
    SessionFenceEvidenceDenied,
    bootstrap_database_roles,
    run_identity_migrations,
    terminate_and_prove_identity_app_sessions_excluded,
    validate_session_fence_evidence,
)
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


@pytest.fixture
def admin_dsn() -> Iterator[str]:
    assert _PG_DSN is not None
    database = f"session_fence_{uuid4().hex}"
    values = conninfo_to_dict(_PG_DSN)
    values["dbname"] = database
    # terminate_and_prove_identity_app_sessions_excluded requires a
    # non-blank credential on the admin DSN (production hygiene, matching
    # every other governed-role DSN check in this codebase); local trust-auth
    # Postgres ignores the password value but this exercises the real check.
    values.setdefault("user", "mak")
    values["password"] = "local-test-admin-credential"
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


def _bootstrap(admin_dsn: str) -> dict[str, str]:
    database = str(conninfo_to_dict(admin_dsn)["dbname"])
    role_dsns = {
        "emg_audit_migrator": _dsn(database, "emg_audit_migrator", "p"),
        "emg_audit_app": _dsn(database, "emg_audit_app", "p"),
        "emg_audit_projector": _dsn(database, "emg_audit_projector", "p"),
        "emg_knowledge_graph_migrator": _dsn(database, "emg_knowledge_graph_migrator", "p"),
        "emg_knowledge_graph_app": _dsn(database, "emg_knowledge_graph_app", "p"),
        "emg_identity_migrator": _dsn(database, "emg_identity_migrator", "p"),
        "emg_identity_app": _dsn(database, "emg_identity_app", "p"),
    }
    bootstrap_database_roles(admin_dsn, role_dsns)
    run_identity_migrations(role_dsns["emg_identity_migrator"])
    return role_dsns


@requires_postgres
def test_surviving_session_is_detected_terminated_and_proven_absent(
    admin_dsn: str, tmp_path: Path
) -> None:
    role_dsns = _bootstrap(admin_dsn)

    # A genuine surviving runtime session: hold a live connection open as
    # emg_identity_app, exactly as a stale Identity pod's connection pool
    # would during a recovery window.
    survivor = psycopg.connect(role_dsns["emg_identity_app"])
    survivor.execute("SELECT 1")

    evidence_path = tmp_path / "session-evidence.json"
    evidence = terminate_and_prove_identity_app_sessions_excluded(
        admin_dsn,
        target_environment="integration-test",
        verified_by="test-actor",
        evidence_output=evidence_path,
    )
    assert evidence.zero_runtime_sessions is True
    assert evidence.terminated_count >= 1

    # The held-open connection must now be dead.
    deadline = time.time() + 5
    closed = False
    while time.time() < deadline:
        try:
            survivor.execute("SELECT 1")
        except psycopg.OperationalError:
            closed = True
            break
        time.sleep(0.1)
    assert closed, "emg_identity_app session survived termination"
    survivor.close()

    # The evidence file this function wrote must itself pass the fail-closed
    # validator.
    validated = validate_session_fence_evidence(
        evidence_path, expected_target_environment="integration-test"
    )
    assert validated.zero_runtime_sessions is True


@requires_postgres
def test_repeated_invocation_with_zero_sessions_is_idempotent(
    admin_dsn: str, tmp_path: Path
) -> None:
    _bootstrap(admin_dsn)

    evidence_path = tmp_path / "session-evidence.json"
    evidence = terminate_and_prove_identity_app_sessions_excluded(
        admin_dsn,
        target_environment="integration-test",
        verified_by="test-actor",
        evidence_output=evidence_path,
    )
    assert evidence.zero_runtime_sessions is True
    assert evidence.terminated_count == 0


@requires_postgres
def test_migrator_credential_is_rejected_even_though_it_is_valid(
    admin_dsn: str, tmp_path: Path
) -> None:
    """A real, live, valid emg_identity_migrator DSN must still be rejected:
    it is one of the seven governed roles and lacks the PostgreSQL privilege
    to terminate emg_identity_app's sessions without violating D-2."""

    role_dsns = _bootstrap(admin_dsn)

    evidence_path = tmp_path / "session-evidence.json"
    with pytest.raises(SessionFenceEvidenceDenied, match="governed database-bootstrap"):
        terminate_and_prove_identity_app_sessions_excluded(
            role_dsns["emg_identity_migrator"],
            target_environment="integration-test",
            verified_by="test-actor",
            evidence_output=evidence_path,
        )
    assert not evidence_path.exists()
