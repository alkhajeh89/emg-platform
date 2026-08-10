"""RC-C: tests for tools/backup/emit_metrics.py, the backup/WAL-archive
freshness metric emitter that observability/alerts/emg-platform-alerts.yaml's
emg-backup-recovery group is written against."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / "tools/backup/emit_metrics.py"
SPEC = importlib.util.spec_from_file_location("emit_metrics", MODULE_PATH)
assert SPEC and SPEC.loader
emit_metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(emit_metrics)


def test_backup_success_writes_prometheus_text_format(tmp_path: Path) -> None:
    output = tmp_path / "emg_backup.prom"

    exit_code = emit_metrics.main(
        ["backup-success", "--output", str(output), "--now", "1700000000"]
    )

    assert exit_code == 0
    text = output.read_text()
    assert "# TYPE emg_backup_last_success_timestamp_seconds gauge" in text
    assert "emg_backup_last_success_timestamp_seconds 1700000000.0" in text


def test_verify_result_ok_and_failed_map_to_one_and_zero(tmp_path: Path) -> None:
    output = tmp_path / "emg_backup.prom"

    emit_metrics.main(["verify-result", "--status", "ok", "--output", str(output)])
    assert "emg_backup_last_verify_status 1.0" in output.read_text()

    emit_metrics.main(["verify-result", "--status", "failed", "--output", str(output)])
    assert "emg_backup_last_verify_status 0.0" in output.read_text()


def test_verify_result_without_status_is_a_usage_error(tmp_path: Path) -> None:
    output = tmp_path / "emg_backup.prom"
    try:
        emit_metrics.main(["verify-result", "--output", str(output)])
        raised = False
    except SystemExit as exc:
        raised = True
        assert exc.code == 2
    assert raised


def test_independent_invocations_preserve_each_others_metrics(tmp_path: Path) -> None:
    """Three separate cron jobs (backup, WAL archive, verify) each call this
    script independently; a later call must not erase an earlier one's
    metric."""
    output = tmp_path / "emg_backup.prom"

    emit_metrics.main(["backup-success", "--output", str(output), "--now", "100"])
    emit_metrics.main(["wal-archive-success", "--output", str(output), "--now", "200"])
    emit_metrics.main(["verify-result", "--status", "ok", "--output", str(output)])

    text = output.read_text()
    assert "emg_backup_last_success_timestamp_seconds 100.0" in text
    assert "emg_wal_archive_last_success_timestamp_seconds 200.0" in text
    assert "emg_backup_last_verify_status 1.0" in text


def test_write_is_atomic_via_rename_no_partial_file_left_behind(tmp_path: Path) -> None:
    output = tmp_path / "emg_backup.prom"

    emit_metrics.main(["backup-success", "--output", str(output), "--now", "1"])

    leftover_tmp_files = list(tmp_path.glob("*.tmp.*"))
    assert leftover_tmp_files == []


def test_creates_parent_directories(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "dir" / "emg_backup.prom"

    exit_code = emit_metrics.main(["backup-success", "--output", str(output), "--now", "1"])

    assert exit_code == 0
    assert output.exists()
