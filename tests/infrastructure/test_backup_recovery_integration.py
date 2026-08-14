from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from emg_audit_client import SubmittedAuditEvent, SubmittedCustodyEvent
from emg_audit_pipeline import PostgresAuditEventStore, PostgresCustodyEventStore
from emg_identity.recovery_gate import RecoveryGateDenied, evaluate_recovery_gate
from emg_identity.refresh_tokens import PostgresRefreshTokenStore
from emg_persistence.provisioning import (
    InMemoryApprovedRecoveryAuthority,
    reconcile_identity_recovery,
    rotate_identity_recovery_generation,
)
from emg_persistence.provisioning.database import _validate_identity_recovery_state

ROOT = Path(__file__).parents[2]
BACKUP = ROOT / "tools/backup"


def run(*args: object, env: dict[str, str] | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        [str(arg) for arg in args],
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.skipif(
    os.environ.get("EMG_RUN_POSTGRES_RECOVERY_TESTS") != "1",
    reason="set EMG_RUN_POSTGRES_RECOVERY_TESTS=1 for the real recovery rehearsal",
)
def test_real_backup_full_restore_startup_and_pitr(tmp_path: Path) -> None:
    for command in ("initdb", "pg_ctl", "pg_basebackup", "psql"):
        assert shutil.which(command), f"missing PostgreSQL command: {command}"
    primary, repository = tmp_path / "primary", tmp_path / "repository"
    socket_dir = Path("/tmp")
    repository.mkdir()
    primary_port = port()
    run("initdb", "-D", primary, "--auth=trust", "--no-locale", "--encoding=UTF8")
    archive = BACKUP / "archive-wal.sh"
    with (primary / "postgresql.conf").open("a") as config:
        config.write(
            f"\nlisten_addresses='127.0.0.1'\nport={primary_port}\n"
            "wal_level=replica\narchive_mode=on\narchive_timeout=1\n"
            f"archive_command='EMG_BACKUP_REPOSITORY={repository} "
            f"EMG_BACKUP_ENCRYPT_COMMAND=/bin/cp {archive} %p %f'\n"
        )
    run("pg_ctl", "-D", primary, "-w", "start", "-o", f"-k {socket_dir}")
    try:
        run("createdb", "-h", "localhost", "-p", primary_port, "emg")
        dsn = f"postgresql://localhost:{primary_port}/emg"
        run(
            "psql",
            dsn,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            ROOT / "tools/seed-data/postgres/001_audit_events.sql",
        )
        run(
            "psql",
            dsn,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            ROOT / "tools/seed-data/postgres/002_audit_provenance.sql",
        )
        run(
            "psql",
            dsn,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            ROOT / "tools/seed-data/postgres/003_evidence_custody.sql",
        )
        run(
            "psql",
            dsn,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            ROOT / "tools/seed-data/postgres/006_audit_tenant.sql",
        )
        run(
            "psql",
            dsn,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            ROOT / "tools/seed-data/postgres/007_identity_refresh_tokens.sql",
        )
        identity_migration_dsn = (
            f"postgresql://emg_identity_migrator:local-test@localhost:{primary_port}/emg"
        )
        run(
            ROOT / ".venv/bin/python",
            "-c",
            "from emg_persistence.provisioning import run_identity_migrations; "
            "import os; run_identity_migrations(os.environ['IDENTITY_DSN'])",
            env={**os.environ, "IDENTITY_DSN": identity_migration_dsn},
        )
        # ADR-043 Amendment 1 A8: establish the initial (generation,
        # authority_revision) pair via a deterministic test-double authority
        # (mechanism 3a: genuine atomic CAS) before any refresh state exists,
        # as bootstrap requires.
        authority = InMemoryApprovedRecoveryAuthority()
        initial_pair = authority.read_current()
        reconcile_identity_recovery(
            identity_migration_dsn, initial_pair.generation, initial_pair.authority_revision
        )
        run(
            "psql",
            identity_migration_dsn,
            "-c",
            "INSERT INTO emg_identity.identity_refresh_token_families (family_hash) "
            "VALUES ('restored-family'); INSERT INTO emg_identity.identity_refresh_tokens "
            "(token_hash, family_hash, status, expires_at) VALUES "
            "('restored-token', 'restored-family', 'active', "
            "clock_timestamp() + interval '1 hour')",
        )
        run("psql", dsn, "-c", "CREATE TABLE recovery_markers(id integer PRIMARY KEY)")
        with psycopg.connect(dsn) as connection:
            audit = PostgresAuditEventStore(connection)
            for index in range(3):
                audit.append(
                    SubmittedAuditEvent(
                        event_id=f"recovery-{index}",
                        actor="recovery-test",
                        actor_type="service",
                        module="recovery",
                        action="anchor",
                        outcome="success",
                        source_system="integration-test",
                    ),
                    source_principal="recovery-test",
                    tenant_id="integration",
                )
            PostgresCustodyEventStore(connection).append(
                SubmittedCustodyEvent(
                    custody_event_id="custody-recovery-1",
                    evidence_id="evidence-1",
                    custody_action="acquire",
                    custodian="recovery-test",
                ),
                source_principal="recovery-test",
            )
        env = {
            **os.environ,
            "EMG_BACKUP_REPOSITORY": str(repository),
            "EMG_BACKUP_DSN": dsn,
            "EMG_BACKUP_ENCRYPT_COMMAND": "/bin/cp",
            "EMG_MANIFEST_SIGN_COMMAND": "/bin/cp",
            "EMG_MANIFEST_VERIFY_COMMAND": "/usr/bin/cmp",
            "EMG_BACKUP_KEY_REFERENCE": "integration-test-key",
            "EMG_BACKUP_PYTHON": str(ROOT / ".venv/bin/python"),
            "EMG_BACKUP_ID": "integration-base",
        }
        run(BACKUP / "scheduled-backup.sh", env=env)
        backup_dir = repository / "full/integration-base"
        assert (repository / "recovery-evidence/integration-base.json").is_file()
        # ADR-043 Amendment 1 A7 replay-resistance proof, step (B)/(C): the
        # external authority legitimately advances AFTER this backup was
        # taken, via the same CAS-protected rotation the accepted A3.2
        # algorithm uses. The backup below carries only the superseded
        # (generation, authority_revision) pair.
        rotated_pair = rotate_identity_recovery_generation(authority)
        run("psql", dsn, "-c", "INSERT INTO recovery_markers VALUES (1)")
        time.sleep(1)
        target = run(
            "psql",
            dsn,
            "-Atqc",
            "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC',"
            '\'YYYY-MM-DD"T"HH24:MI:SS"Z"\')',
            capture=True,
        )
        time.sleep(2)
        run("psql", dsn, "-c", "INSERT INTO recovery_markers VALUES (2)")
        run("psql", dsn, "-c", "SELECT pg_switch_wal()")
        deadline = time.time() + 20
        while time.time() < deadline and not list((repository / "wal").glob("*.integrity.json")):
            time.sleep(0.2)
    finally:
        run("pg_ctl", "-D", primary, "-m", "fast", "-w", "stop")

    restore_env = {
        **os.environ,
        "EMG_BACKUP_REPOSITORY": str(repository),
        "EMG_BACKUP_DECRYPT_COMMAND": "/bin/cp",
        "EMG_MANIFEST_VERIFY_COMMAND": "/usr/bin/cmp",
        "EMG_BACKUP_PYTHON": str(ROOT / ".venv/bin/python"),
        "EMG_RECOVERY_MODE": "isolated-restore",
        "EMG_RECOVERY_CONFIRMATION": "RESTORE_INTO_EMPTY_TARGET",
        "EMG_RECOVERY_TARGET_ID": "integration-test",
    }
    full = tmp_path / "full"
    full.mkdir()
    run(BACKUP / "restore-full.sh", backup_dir, full, env=restore_env)
    full_port = port()
    run(
        "pg_ctl",
        "-D",
        full,
        "-w",
        "start",
        "-o",
        f"-p {full_port} -k {socket_dir}",
        env=restore_env,
    )
    run("pg_ctl", "-D", full, "-m", "fast", "-w", "stop")

    pitr = tmp_path / "pitr"
    pitr.mkdir()
    run(BACKUP / "restore-pitr.sh", backup_dir, pitr, target, "promote", env=restore_env)
    pitr_port = port()
    run(
        "pg_ctl",
        "-D",
        pitr,
        "-w",
        "start",
        "-o",
        f"-p {pitr_port} -k {socket_dir}",
        env=restore_env,
    )
    restored_dsn = f"postgresql://localhost:{pitr_port}/emg"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if (
                run("psql", restored_dsn, "-Atqc", "SELECT pg_is_in_recovery()", capture=True)
                == "f"
            ):
                break
            time.sleep(0.2)
        else:
            pytest.fail("PITR did not reach and promote the configured target")
        assert (
            run(
                "psql", restored_dsn, "-Atqc", "SELECT count(*) FROM recovery_markers", capture=True
            )
            == "1"
        )
        # ADR-043 Amendment 1 A7(E)/A8: before reconciliation, the restored
        # database's recovery-state row is still the superseded pair; the
        # live authority (materialized here as a fresh-Identity-workload
        # authority file) has already advanced. Readiness and every
        # refresh-token operation must fail closed against this mismatch.
        restored_app_dsn = f"postgresql://emg_identity_app:local-test@localhost:{pitr_port}/emg"
        stale_authority_file = tmp_path / "post-rotation-authority.json"
        stale_authority_file.write_text(
            f'{{"generation": "{rotated_pair.generation}", '
            f'"authority_revision": "{rotated_pair.authority_revision}"}}',
            encoding="utf-8",
        )
        with pytest.raises(RecoveryGateDenied):
            evaluate_recovery_gate(dsn=restored_app_dsn, authority_file=stale_authority_file)
        pre_reconciliation_store = PostgresRefreshTokenStore(
            restored_app_dsn, recovery_authority_file=stale_authority_file
        )
        with pytest.raises(RecoveryGateDenied):
            pre_reconciliation_store.family_is_active("restored-family")
        verify_env = {
            **restore_env,
            "EMG_RESTORE_DSN": restored_dsn,
            "EMG_IDENTITY_RECOVERY_DSN": (
                f"postgresql://emg_identity_migrator:local-test@localhost:{pitr_port}/emg"
            ),
            "EMG_IDENTITY_RECOVERY_GENERATION": rotated_pair.generation,
            "EMG_IDENTITY_RECOVERY_AUTHORITY_REVISION": rotated_pair.authority_revision,
            "EMG_EXPECTED_PITR_TARGET_TIME": target,
            "EMG_RECOVERY_ASSERT_SQL": "SELECT count(*)=1 FROM recovery_markers",
        }
        run(BACKUP / "verify-recovery.sh", backup_dir / "manifest.json", env=verify_env)
        assert (
            run(
                "psql",
                verify_env["EMG_IDENTITY_RECOVERY_DSN"],
                "-Atqc",
                "SELECT bool_and(revoked_at IS NOT NULL) FROM "
                "emg_identity.identity_refresh_token_families",
                capture=True,
            )
            == "t"
        )
        # A6/A7(E): the reconciliation transaction, run above via the
        # governed shell entrypoint, must have recorded exactly the rotated
        # (generation, authority_revision) pair -- never left the restored,
        # superseded pair active.
        assert (
            run(
                "psql",
                verify_env["EMG_IDENTITY_RECOVERY_DSN"],
                "-Atqc",
                "SELECT reconciled_generation, reconciled_authority_revision "
                "FROM emg_identity.identity_recovery_state",
                capture=True,
            )
            == f"{rotated_pair.generation}|{rotated_pair.authority_revision}"
        )
        assert (
            run(
                "psql",
                verify_env["EMG_IDENTITY_RECOVERY_DSN"],
                "-Atqc",
                "SELECT count(*) FROM emg_identity.identity_recovery_state",
                capture=True,
            )
            == "1"
        )
        # Stage-50 recovery validation (A11): the recovery relation's exact
        # structure, ownership, and security state. The full cross-stream
        # ADR-041 role-set check in _validate_identity_database is exercised
        # separately by test_rc1h_provisioning_integration.py, which runs
        # the complete bootstrap flow this lighter seed-based recovery
        # rehearsal does not.
        with (
            psycopg.connect(verify_env["EMG_IDENTITY_RECOVERY_DSN"]) as connection,
            connection.cursor() as cursor,
        ):
            _validate_identity_recovery_state(cursor)

        # A8: a fresh Identity workload, materializing the now-current
        # rotated pair, reaches READY only now -- never before reconciliation.
        fresh_authority_file = tmp_path / "post-reconciliation-authority.json"
        fresh_authority_file.write_text(
            f'{{"generation": "{rotated_pair.generation}", '
            f'"authority_revision": "{rotated_pair.authority_revision}"}}',
            encoding="utf-8",
        )
        evaluate_recovery_gate(dsn=restored_app_dsn, authority_file=fresh_authority_file)

        # D-10/A7: the restored refresh credential remains rejected even
        # after reconciliation succeeds and the gate opens.
        post_reconciliation_store = PostgresRefreshTokenStore(
            restored_app_dsn, recovery_authority_file=fresh_authority_file
        )
        assert post_reconciliation_store.family_is_active("restored-family") is False
        assert (
            post_reconciliation_store.rotate(
                "restored-family",
                "restored-token",
                "post-recovery-token",
                datetime.now(timezone.utc) + timedelta(hours=1),
            )
            is False
        )

        run("psql", restored_dsn, "-c", "DELETE FROM audit_events WHERE sequence_number=3")
        tampered = subprocess.run(
            [str(BACKUP / "verify-recovery.sh"), str(backup_dir / "manifest.json")],
            env=verify_env,
            check=False,
        )
        assert tampered.returncode != 0, "tail truncation must fail evidence-anchor verification"
    finally:
        run("pg_ctl", "-D", pitr, "-m", "fast", "-w", "stop")
