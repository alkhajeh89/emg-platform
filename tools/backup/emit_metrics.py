#!/usr/bin/env python3
"""Emit PostgreSQL backup/WAL-archive freshness metrics for the
`node_exporter` textfile collector convention (RC-C, EMG v1 RC closure).

Why this exists: docs/operations/postgresql-backup-recovery.md documents a
concrete, already-governed alerting requirement ("Alert on backup age over
24 hours, WAL archive age over five minutes, checksum failure") but nothing
in this repository emitted a metric those thresholds could be evaluated
against. `observability/alerts/emg-platform-alerts.yaml`'s emg-backup-recovery
group is written against the metric names this script emits.

Why a standalone script, not `emg_telemetry.metrics`: `tools/backup/*.sh`
run in whatever environment operates PostgreSQL backups, which is not
guaranteed to have the `emg-*` Python package tree installed (these are
ops/infra scripts, not an EMG service). This script depends on nothing
beyond the Python 3 standard library, matching every other script in this
directory.

Why the textfile-collector convention specifically (rather than pushing to a
long-running HTTP endpoint): `full-backup.sh` / `archive-wal.sh` /
`verify-backup.sh` are one-shot, cron-invoked processes with no long-lived
process to serve an HTTP `/metrics` endpoint from — the same shape of
problem the headless `audit-projector` worker had before this change added
`emg_audit_projector.metrics_server`, except here there is no long-running
process at all to attach a server to. The textfile collector is
node_exporter's standard, widely-documented answer to exactly this: a
batch/cron job atomically writes a small `.prom` file to a well-known
directory, and node_exporter (if deployed and configured with
`--collector.textfile.directory`) reads and re-exposes it on its own
`/metrics` alongside host metrics. Deploying node_exporter with that
collector enabled, and pointing this script's `--output` at the directory
it watches, is an operational wiring decision (bucket B) this script does
not make -- it only produces a correctly-formatted file at a path the
caller controls.

Usage (called from the relevant tools/backup/*.sh after each run):

    python3 emit_metrics.py backup-success [--output PATH]
    python3 emit_metrics.py wal-archive-success [--output PATH]
    python3 emit_metrics.py verify-result --status ok|failed [--output PATH]

Each invocation atomically rewrites the *entire* output file, preserving
whichever of the three metrics it did not just update by reading the
previous file first -- so three separate cron jobs (full backup, WAL
archive, verification) calling this script independently converge on one
consistent file rather than clobbering each other's last-known values.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

DEFAULT_OUTPUT = Path("/var/lib/node_exporter/textfile_collector/emg_backup.prom")

_METRIC_HELP = {
    "emg_backup_last_success_timestamp_seconds": (
        "Unix timestamp of the last successful full PostgreSQL backup."
    ),
    "emg_wal_archive_last_success_timestamp_seconds": (
        "Unix timestamp of the last successfully archived WAL segment."
    ),
    "emg_backup_last_verify_status": (
        "1 if the most recent backup passed checksum/manifest verification, 0 if it failed."
    ),
}
_METRIC_TYPE = {
    "emg_backup_last_success_timestamp_seconds": "gauge",
    "emg_wal_archive_last_success_timestamp_seconds": "gauge",
    "emg_backup_last_verify_status": "gauge",
}
_VALUE_LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([0-9.eE+\-]+)\s*$")


def _read_existing(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    try:
        text = path.read_text()
    except FileNotFoundError:
        return values
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        match = _VALUE_LINE.match(line)
        if match:
            values[match.group(1)] = float(match.group(2))
    return values


def _render(values: dict[str, float]) -> str:
    lines: list[str] = []
    for name in sorted(values):
        help_text = _METRIC_HELP.get(name, "")
        metric_type = _METRIC_TYPE.get(name, "gauge")
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")
        lines.append(f"{name} {values[name]}")
    return "\n".join(lines) + "\n" if lines else ""


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(content)
    os.replace(tmp_path, path)  # atomic on the same filesystem


def _update(output: Path, updates: dict[str, float]) -> None:
    values = _read_existing(output)
    values.update(updates)
    _write_atomic(output, _render(values))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("backup-success", "wal-archive-success", "verify-result")
    )
    parser.add_argument("--status", choices=("ok", "failed"), default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--now",
        type=float,
        default=None,
        help="Override the recorded timestamp (seconds since epoch); for tests only.",
    )
    args = parser.parse_args(argv)
    now = args.now if args.now is not None else time.time()

    if args.command == "backup-success":
        _update(args.output, {"emg_backup_last_success_timestamp_seconds": now})
    elif args.command == "wal-archive-success":
        _update(args.output, {"emg_wal_archive_last_success_timestamp_seconds": now})
    elif args.command == "verify-result":
        if args.status is None:
            parser.error("verify-result requires --status ok|failed")
        _update(
            args.output,
            {"emg_backup_last_verify_status": 1.0 if args.status == "ok" else 0.0},
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
