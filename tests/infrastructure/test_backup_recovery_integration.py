from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import psycopg
import pytest
from emg_audit_client import SubmittedAuditEvent, SubmittedCustodyEvent
from emg_audit_pipeline import PostgresAuditEventStore, PostgresCustodyEventStore

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
        verify_env = {
            **restore_env,
            "EMG_RESTORE_DSN": restored_dsn,
            "EMG_EXPECTED_PITR_TARGET_TIME": target,
            "EMG_RECOVERY_ASSERT_SQL": "SELECT count(*)=1 FROM recovery_markers",
        }
        run(BACKUP / "verify-recovery.sh", backup_dir / "manifest.json", env=verify_env)
        run("psql", restored_dsn, "-c", "DELETE FROM audit_events WHERE sequence_number=3")
        tampered = subprocess.run(
            [str(BACKUP / "verify-recovery.sh"), str(backup_dir / "manifest.json")],
            env=verify_env,
            check=False,
        )
        assert tampered.returncode != 0, "tail truncation must fail evidence-anchor verification"
    finally:
        run("pg_ctl", "-D", pitr, "-m", "fast", "-w", "stop")
