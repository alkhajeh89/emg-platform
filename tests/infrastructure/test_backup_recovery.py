from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / "tools/backup/backup_manifest.py"
SPEC = importlib.util.spec_from_file_location("backup_manifest", MODULE_PATH)
assert SPEC and SPEC.loader
backup_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup_manifest)


def manifest(directory: Path, backup_id: str = "backup") -> dict[str, object]:
    artifacts = []
    for role, name in (("base", "base.tar.gz.enc"), ("wal", "pg_wal.tar.gz.enc")):
        path = directory / name
        path.write_bytes(role.encode())
        artifacts.append(
            {
                "role": role,
                "path": name,
                "size": path.stat().st_size,
                "sha256": backup_manifest.digest(path),
                "encrypted": True,
            }
        )
    return {
        "schemaVersion": 2,
        "backupId": backup_id,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "postgres": {
            "majorVersion": 16,
            "startLsn": "0/1000000",
            "stopLsn": "0/2000000",
            "startWal": "000000010000000000000001",
            "stopWal": "000000010000000000000002",
            "database": "emg",
        },
        "encryption": {"required": True, "keyReference": "test-key"},
        "artifacts": artifacts,
        "tablespaces": [],
        "evidenceAnchors": {
            "audit": {"rowCount": 0, "terminalSequence": None, "terminalHash": None},
            "custody": {"rowCount": 0, "terminalSequence": None, "terminalHash": None},
        },
    }


def write_manifest(directory: Path, backup_id: str = "backup") -> Path:
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest(directory, backup_id)))
    return path


def test_config_contracts_parse() -> None:
    backup = yaml.safe_load((ROOT / "infra/backup/backup.example.yaml").read_text())
    restore = yaml.safe_load((ROOT / "infra/backup/restore.example.yaml").read_text())
    assert backup["spec"]["objectives"] == {"rpoMinutes": 5, "rtoMinutes": 240}
    assert restore["spec"]["verification"]["requireEvidenceLedgerIntegrity"] is True


def test_manifest_requires_roles_and_detects_corruption(tmp_path: Path) -> None:
    path = write_manifest(tmp_path)
    assert backup_manifest.load_manifest(path, verify_files=True)["schemaVersion"] == 2
    (tmp_path / "base.tar.gz.enc").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        backup_manifest.load_manifest(path, verify_files=True)


def test_arbitrary_artifact_cannot_describe_backup(tmp_path: Path) -> None:
    data = manifest(tmp_path)
    data["artifacts"] = [data["artifacts"][0]]
    with pytest.raises(ValueError, match="exactly one"):
        backup_manifest.validate_manifest(data)


def test_schema_and_runtime_validator_share_conformance_corpus(tmp_path: Path) -> None:
    schema = json.loads((ROOT / "infra/backup/manifest.schema.json").read_text())
    valid = manifest(tmp_path)
    jsonschema.Draft202012Validator(schema).validate(valid)
    backup_manifest.validate_manifest(valid)
    invalid = {**valid, "artifacts": [valid["artifacts"][0]]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)
    with pytest.raises(ValueError):
        backup_manifest.validate_manifest(invalid)


def test_schema_accepts_a_populated_evidence_anchor(tmp_path: Path) -> None:
    """Backward-compatibility proof for the schema's new if/then/else anchor
    constraint: a genuinely non-empty, internally-consistent anchor (the
    'else' branch) must still validate against both the schema and the
    runtime validator, not just the all-zero anchor every other fixture in
    this file uses."""
    schema = json.loads((ROOT / "infra/backup/manifest.schema.json").read_text())
    valid = manifest(tmp_path)
    valid["evidenceAnchors"]["audit"] = {
        "rowCount": 3,
        "terminalSequence": 3,
        "terminalHash": "a" * 64,
    }
    jsonschema.Draft202012Validator(schema).validate(valid)
    backup_manifest.validate_manifest(valid)


def test_schema_rejects_inconsistent_evidence_anchor(tmp_path: Path) -> None:
    """H-1 parity fix: a non-empty rowCount with null terminal fields is
    rejected by both the runtime validator and the schema. Previously the
    schema accepted this (RC-1B independent verification finding H-1)."""
    schema = json.loads((ROOT / "infra/backup/manifest.schema.json").read_text())
    invalid = manifest(tmp_path)
    invalid["evidenceAnchors"]["audit"] = {
        "rowCount": 5,
        "terminalSequence": None,
        "terminalHash": None,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)
    with pytest.raises(ValueError):
        backup_manifest.validate_manifest(invalid)


def test_schema_rejects_zero_row_count_with_non_null_terminal(tmp_path: Path) -> None:
    """The inverse inconsistency: an empty anchor must not carry a terminal
    sequence/hash either. Covers the schema's 'if rowCount==0' branch, not
    only the 'else' branch covered above."""
    schema = json.loads((ROOT / "infra/backup/manifest.schema.json").read_text())
    invalid = manifest(tmp_path)
    invalid["evidenceAnchors"]["custody"] = {
        "rowCount": 0,
        "terminalSequence": 1,
        "terminalHash": "b" * 64,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)
    with pytest.raises(ValueError):
        backup_manifest.validate_manifest(invalid)


def test_schema_rejects_non_utc_created_at(tmp_path: Path) -> None:
    """H-1-adjacent parity fix found while closing H-1: backup_manifest.py's
    _utc() requires a literal 'Z' suffix and rejects any other RFC3339
    offset, but the schema's bare 'format: date-time' accepted one. Now
    rejected by both."""
    schema = json.loads((ROOT / "infra/backup/manifest.schema.json").read_text())
    invalid = manifest(tmp_path)
    invalid["createdAt"] = "2025-01-01T01:00:00+04:00"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)
    with pytest.raises(ValueError):
        backup_manifest.validate_manifest(invalid)


def test_schema_accepts_fractional_seconds_utc_created_at(tmp_path: Path) -> None:
    """Backward-compatibility proof for the tightened createdAt pattern:
    fractional seconds are permitted by _utc() (via datetime.fromisoformat)
    as long as the string still ends in a literal 'Z' -- the schema pattern
    must not be stricter than the runtime validator in this direction."""
    schema = json.loads((ROOT / "infra/backup/manifest.schema.json").read_text())
    valid = manifest(tmp_path)
    valid["createdAt"] = "2025-01-01T01:00:00.123456Z"
    jsonschema.Draft202012Validator(schema).validate(valid)
    backup_manifest.validate_manifest(valid)


def test_duplicate_tablespace_oid_with_differing_restore_path_is_python_only(
    tmp_path: Path,
) -> None:
    """Documents a KNOWN, INTENTIONAL residual gap, not a regression: JSON
    Schema (any draft) cannot express 'array of objects unique by one
    sub-field, with other fields allowed to differ' without restructuring
    the array into an object keyed by that field -- which would change the
    manifest format and is out of scope for a schema-only correction. The
    runtime validator remains, and is documented as, the sole enforcement
    point for this rule; every operational script already calls it (never
    schema-validate alone) for exactly this reason. This test exists so a
    future change to either validator's behaviour here is caught explicitly
    rather than silently drifting.
    """
    schema = json.loads((ROOT / "infra/backup/manifest.schema.json").read_text())
    invalid = manifest(tmp_path)
    invalid["tablespaces"] = [
        {"oid": "16384", "restorePath": "/data/ts1"},
        {"oid": "16384", "restorePath": "/data/ts2"},
    ]
    invalid["artifacts"].append(
        {
            "role": "tablespace",
            "path": "16384.tar.gz.enc",
            "size": 1,
            "sha256": "c" * 64,
            "encrypted": True,
            "tablespaceOid": "16384",
        }
    )
    with pytest.raises(ValueError, match="duplicate"):
        backup_manifest.validate_manifest(invalid)
    jsonschema.Draft202012Validator(schema).validate(invalid)


def test_pitr_config_is_utc_and_deterministic() -> None:
    output = backup_manifest.pitr_config(
        "2025-01-02T03:04:05Z", "/opt/emg/restore-wal.sh", "promote"
    )
    assert "recovery_target_time = '2025-01-02 03:04:05+00'" in output
    with pytest.raises(ValueError, match="canonical UTC"):
        backup_manifest.pitr_config("2025-01-02T03:04:05+04:00", "/x", "promote")


def test_retention_uses_only_verified_backups_and_stable_plan(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    for index in range(3):
        child = tmp_path / f"backup-{index}"
        child.mkdir()
        data = manifest(child, child.name)
        data["createdAt"] = (now.replace(microsecond=0)).isoformat().replace("+00:00", "Z")
        (child / "manifest.json").write_text(json.dumps(data))
    invalid = tmp_path / "backup-invalid"
    invalid.mkdir()
    (invalid / "manifest.json").write_text("{}")
    now_text = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    first = backup_manifest.retention_plan(tmp_path, now_text, 35, 2)
    second = backup_manifest.retention_plan(tmp_path, now_text, 35, 2)
    assert first == second
    assert len(first["state"]) == 3


def test_retention_apply_requires_reviewed_plan_and_deletes_only_verified(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    full = repository / "full"
    full.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    for index, age in enumerate((60, 10, 5)):
        child = full / f"backup-{index}"
        child.mkdir()
        data = manifest(child, child.name)
        data["createdAt"] = (now - timedelta(days=age)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (child / "manifest.json").write_text(json.dumps(data))
    env = {
        **os.environ,
        "EMG_BACKUP_REPOSITORY": str(repository),
        "EMG_RETENTION_NOW": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "EMG_RETENTION_MINIMUM_DAYS": "35",
        "EMG_RETENTION_MINIMUM_COUNT": "2",
    }
    script = ROOT / "tools/backup/retention.sh"
    plan = json.loads(
        subprocess.run([script], env=env, check=True, capture_output=True, text=True).stdout
    )
    assert subprocess.run([script, "--apply", "0" * 64], env=env).returncode != 0
    subprocess.run([script, "--apply", plan["planId"]], env=env, check=True)
    assert not (full / "backup-0").exists()
    assert (full / "backup-1").exists() and (full / "backup-2").exists()


def test_wal_archive_duplicate_corruption_and_history(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    source = tmp_path / "wal"
    source.write_bytes(b"wal")
    env = {
        **os.environ,
        "EMG_BACKUP_REPOSITORY": str(repository),
        "EMG_BACKUP_ENCRYPT_COMMAND": "/bin/cp",
    }
    script = ROOT / "tools/backup/archive-wal.sh"
    subprocess.run([script, source, "000000010000000000000001"], env=env, check=True)
    subprocess.run([script, source, "000000010000000000000001"], env=env, check=True)
    (repository / "wal/000000010000000000000001.enc").write_bytes(b"bad")
    assert subprocess.run([script, source, "000000010000000000000001"], env=env).returncode != 0
    history = tmp_path / "history"
    history.write_bytes(b"history")
    subprocess.run([script, history, "00000002.history"], env=env, check=True)


def test_all_shell_scripts_parse() -> None:
    for script in sorted((ROOT / "tools/backup").glob("*.sh")):
        subprocess.run(["bash", "-n", script], check=True)


def test_restore_requires_explicit_isolated_target_authorization(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    script = ROOT / "tools/backup/restore-full.sh"
    env = {
        **os.environ,
        "EMG_BACKUP_DECRYPT_COMMAND": "/bin/cp",
        "EMG_MANIFEST_VERIFY_COMMAND": "/bin/true",
    }
    result = subprocess.run([script, tmp_path, target], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "EMG_RECOVERY_MODE" in result.stderr
    env.update(
        EMG_RECOVERY_MODE="isolated-restore",
        EMG_RECOVERY_CONFIRMATION="RESTORE_INTO_EMPTY_TARGET",
        EMG_RECOVERY_TARGET_ID="production",
    )
    result = subprocess.run([script, tmp_path, target], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "active production" in result.stderr


def test_scheduled_backup_failure_is_machine_readable_and_fail_closed(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    env = {
        **os.environ,
        "EMG_BACKUP_REPOSITORY": str(repository),
        "EMG_MANIFEST_VERIFY_COMMAND": "/bin/false",
        "EMG_BACKUP_DSN": "postgresql://unreachable.invalid/emg",
        "EMG_BACKUP_ENCRYPT_COMMAND": "/bin/false",
        "EMG_MANIFEST_SIGN_COMMAND": "/bin/false",
        "EMG_BACKUP_KEY_REFERENCE": "test-key",
        "EMG_BACKUP_ID": "failure-test",
    }
    result = subprocess.run(
        [ROOT / "tools/backup/scheduled-backup.sh"], env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    event = json.loads(result.stderr.strip().splitlines()[-1])
    assert event["event"] == "emg.recovery.backup.failed"
    assert event["backupId"] == "failure-test"
    assert not (repository / "recovery-evidence/failure-test.json").exists()
