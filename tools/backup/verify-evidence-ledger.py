#!/usr/bin/env python3
"""Verify both restored EMG evidence hash chains using production algorithms."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def verify_ledgers(
    connection: object, audit_store: type, custody_store: type, anchors: dict[str, object]
) -> dict[str, object]:
    audit = audit_store(connection).verify_integrity()
    custody = custody_store(connection).verify_integrity()
    with connection.cursor() as cursor:
        observed = {}
        for name, table, sequence in (
            ("audit", "audit_events", "sequence_number"),
            ("custody", "evidence_custody_events", "chain_sequence"),
        ):
            cursor.execute(f"SELECT count(*), max({sequence}) FROM {table}")
            count, terminal = cursor.fetchone()
            cursor.execute(f"SELECT event_hash FROM {table} ORDER BY {sequence} DESC LIMIT 1")
            row = cursor.fetchone()
            observed[name] = {
                "rowCount": int(count),
                "terminalSequence": None if terminal is None else int(terminal),
                "terminalHash": None if row is None else str(row[0]),
            }
    anchor_match = observed == anchors
    return {
        "audit": audit.__dict__,
        "custody": custody.__dict__,
        "anchors": {"expected": anchors, "observed": observed, "match": anchor_match},
        "intact": audit.intact and custody.intact and anchor_match,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True, help="Secret-managed DSN for the restored database")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        import psycopg
        from backup_manifest import load_manifest
        from emg_audit_pipeline import PostgresAuditEventStore, PostgresCustodyEventStore

        anchors = load_manifest(args.manifest)["evidenceAnchors"]
        with psycopg.connect(args.dsn) as connection:
            result = verify_ledgers(
                connection, PostgresAuditEventStore, PostgresCustodyEventStore, anchors
            )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["intact"] else 1
    except Exception as exc:
        print(json.dumps({"intact": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
