#!/usr/bin/env python3
"""Build an RC-1B manifest from PostgreSQL's authoritative backup manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg
from backup_manifest import digest, validate_manifest


def anchor(connection: psycopg.Connection[object], table: str, sequence: str) -> dict[str, object]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        if cursor.fetchone()[0] is None:
            return {"rowCount": 0, "terminalSequence": None, "terminalHash": None}
        cursor.execute(f"SELECT count(*), max({sequence}) FROM {table}")
        count, terminal = cursor.fetchone()
        if int(count) == 0:
            return {"rowCount": 0, "terminalSequence": None, "terminalHash": None}
        cursor.execute(f"SELECT event_hash FROM {table} ORDER BY {sequence} DESC LIMIT 1")
        return {
            "rowCount": int(count),
            "terminalSequence": int(terminal),
            "terminalHash": str(cursor.fetchone()[0]),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-manifest", type=Path, required=True)
    parser.add_argument("--artifact-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--key-reference", required=True)
    parser.add_argument("--tablespaces-json", default="[]")
    args = parser.parse_args()
    pg_data = json.loads(args.pg_manifest.read_text(encoding="utf-8"))
    ranges = pg_data.get("WAL-Ranges", [])
    if len(ranges) != 1:
        raise SystemExit("backup manifest must contain exactly one WAL range")
    start_lsn, stop_lsn = ranges[0]["Start-LSN"], ranges[0]["End-LSN"]
    tablespaces = json.loads(args.tablespaces_json)
    mappings = {str(item["oid"]): str(item["restorePath"]) for item in tablespaces}
    artifacts = []
    for path in sorted(args.artifact_directory.glob("*.enc")):
        plain = path.name.removesuffix(".enc")
        if plain == "base.tar.gz":
            role, oid = "base", None
        elif plain == "pg_wal.tar.gz":
            role, oid = "wal", None
        elif plain == "backup_manifest":
            role, oid = "postgres-manifest", None
        elif plain.removesuffix(".tar.gz").isdigit():
            role, oid = "tablespace", plain.removesuffix(".tar.gz")
            if oid not in mappings:
                raise SystemExit(f"missing restore mapping for tablespace {oid}")
        else:
            raise SystemExit(f"unknown pg_basebackup artifact: {plain}")
        item = {
            "role": role,
            "path": path.name,
            "size": path.stat().st_size,
            "sha256": digest(path),
            "encrypted": True,
        }
        if oid is not None:
            item["tablespaceOid"] = oid
        artifacts.append(item)
    with psycopg.connect(args.dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('server_version_num')::integer / 10000, "
                "current_database(), pg_walfile_name(%s::pg_lsn), "
                "pg_walfile_name(%s::pg_lsn)",
                (start_lsn, stop_lsn),
            )
            major, database, start_wal, stop_wal = cursor.fetchone()
        anchors = {
            "audit": anchor(connection, "audit_events", "sequence_number"),
            "custody": anchor(connection, "evidence_custody_events", "chain_sequence"),
        }
    data = {
        "schemaVersion": 2,
        "backupId": args.backup_id,
        "createdAt": args.created_at,
        "postgres": {
            "majorVersion": int(major),
            "startLsn": start_lsn,
            "stopLsn": stop_lsn,
            "startWal": start_wal,
            "stopWal": stop_wal,
            "database": database,
        },
        "encryption": {"required": True, "keyReference": args.key_reference},
        "artifacts": artifacts,
        "tablespaces": tablespaces,
        "evidenceAnchors": anchors,
    }
    validate_manifest(data)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
