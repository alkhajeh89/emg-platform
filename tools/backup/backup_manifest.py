#!/usr/bin/env python3
"""Provider-neutral PostgreSQL backup manifests and retention plans."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BACKUP_ID = re.compile(r"^[A-Za-z0-9._-]+$")
LSN = re.compile(r"^[0-9A-F]+/[0-9A-F]+$")
WAL = re.compile(r"^[0-9A-F]{24}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ROLES = {"base", "wal", "postgres-manifest", "tablespace"}


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _utc(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("time must be canonical UTC ending in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("time must be UTC")
    return parsed


def _anchor(value: Any, name: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "rowCount",
        "terminalSequence",
        "terminalHash",
    }:
        raise ValueError(f"invalid {name} evidence anchor")
    count, sequence, terminal_hash = (
        value["rowCount"],
        value["terminalSequence"],
        value["terminalHash"],
    )
    if not isinstance(count, int) or count < 0:
        raise ValueError(f"invalid {name} row count")
    if count == 0 and (sequence is not None or terminal_hash is not None):
        raise ValueError(f"empty {name} anchor must have null terminal values")
    if count > 0 and (
        not isinstance(sequence, int)
        or sequence < 1
        or not isinstance(terminal_hash, str)
        or not SHA256.fullmatch(terminal_hash)
    ):
        raise ValueError(f"non-empty {name} anchor requires sequence and hash")


def validate_manifest(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("manifest must be an object")
    expected = {
        "schemaVersion",
        "backupId",
        "createdAt",
        "postgres",
        "encryption",
        "artifacts",
        "tablespaces",
        "evidenceAnchors",
    }
    if set(data) != expected or data["schemaVersion"] != 2:
        raise ValueError("manifest fields or schema version are invalid")
    if not isinstance(data["backupId"], str) or not BACKUP_ID.fullmatch(data["backupId"]):
        raise ValueError("invalid backupId")
    _utc(str(data["createdAt"]))
    postgres = data["postgres"]
    if not isinstance(postgres, dict) or set(postgres) != {
        "majorVersion",
        "startLsn",
        "stopLsn",
        "startWal",
        "stopWal",
        "database",
    }:
        raise ValueError("invalid PostgreSQL metadata")
    if not isinstance(postgres["majorVersion"], int) or postgres["majorVersion"] < 14:
        raise ValueError("invalid PostgreSQL major version")
    if not LSN.fullmatch(str(postgres["startLsn"])) or not LSN.fullmatch(str(postgres["stopLsn"])):
        raise ValueError("invalid backup LSN boundary")
    if not WAL.fullmatch(str(postgres["startWal"])) or not WAL.fullmatch(str(postgres["stopWal"])):
        raise ValueError("invalid backup WAL boundary")
    if not isinstance(postgres["database"], str) or not postgres["database"]:
        raise ValueError("invalid database identity")
    encryption = data["encryption"]
    if (
        not isinstance(encryption, dict)
        or encryption.get("required") is not True
        or not encryption.get("keyReference")
    ):
        raise ValueError("encrypted backup and key reference are required")
    tablespaces = data["tablespaces"]
    if not isinstance(tablespaces, list):
        raise ValueError("tablespaces must be an array")
    mappings: dict[str, str] = {}
    for mapping in tablespaces:
        if not isinstance(mapping, dict) or set(mapping) != {"oid", "restorePath"}:
            raise ValueError("invalid tablespace mapping")
        oid, target = str(mapping["oid"]), str(mapping["restorePath"])
        if not oid.isdigit() or not Path(target).is_absolute() or oid in mappings:
            raise ValueError("unsafe or duplicate tablespace mapping")
        mappings[oid] = target
    artifacts = data["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("artifacts must be an array")
    roles: list[str] = []
    seen: set[str] = set()
    table_oids: set[str] = set()
    for artifact in artifacts:
        required = {"role", "path", "size", "sha256", "encrypted"}
        allowed = required | {"tablespaceOid"}
        if (
            not isinstance(artifact, dict)
            or not required.issubset(artifact)
            or set(artifact) - allowed
        ):
            raise ValueError("invalid artifact")
        role, name = str(artifact["role"]), str(artifact["path"])
        if role not in ROLES or name in seen or Path(name).name != name:
            raise ValueError("unknown role or unsafe/duplicate artifact path")
        if (
            artifact["encrypted"] is not True
            or not isinstance(artifact["size"], int)
            or artifact["size"] < 1
        ):
            raise ValueError("artifact must be non-empty and encrypted")
        if not isinstance(artifact["sha256"], str) or not SHA256.fullmatch(artifact["sha256"]):
            raise ValueError("invalid artifact checksum")
        if role == "tablespace":
            oid = str(artifact.get("tablespaceOid", ""))
            if oid not in mappings or oid in table_oids:
                raise ValueError("tablespace artifact lacks a unique validated mapping")
            table_oids.add(oid)
        elif "tablespaceOid" in artifact:
            raise ValueError("tablespaceOid is only valid for tablespace artifacts")
        roles.append(role)
        seen.add(name)
    if roles.count("base") != 1 or roles.count("wal") != 1:
        raise ValueError("manifest requires exactly one base and one WAL archive")
    if table_oids != set(mappings):
        raise ValueError("tablespace mappings and artifacts do not match")
    anchors = data["evidenceAnchors"]
    if not isinstance(anchors, dict) or set(anchors) != {"audit", "custody"}:
        raise ValueError("invalid evidence anchors")
    _anchor(anchors["audit"], "audit")
    _anchor(anchors["custody"], "custody")
    return data


def load_manifest(path: Path, verify_files: bool = False) -> dict[str, Any]:
    data = validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    if verify_files:
        for artifact in data["artifacts"]:
            candidate = (path.parent / artifact["path"]).resolve()
            if path.parent.resolve() not in candidate.parents or not candidate.is_file():
                raise ValueError(f"missing artifact: {artifact['path']}")
            if (
                candidate.stat().st_size != artifact["size"]
                or digest(candidate) != artifact["sha256"]
            ):
                raise ValueError(f"artifact integrity failure: {artifact['path']}")
    return data


def schema_validate(path: Path, schema: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise ValueError("jsonschema package is required for authoritative validation") from exc
    jsonschema.Draft202012Validator.check_schema(json.loads(schema.read_text()))
    jsonschema.Draft202012Validator(
        json.loads(schema.read_text()), format_checker=jsonschema.FormatChecker()
    ).validate(json.loads(path.read_text()))


def retention_plan(
    repository: Path, now_text: str, minimum_days: int, minimum_count: int
) -> dict[str, Any]:
    if minimum_days < 1 or minimum_count < 2:
        raise ValueError("retention requires at least one day and two valid backups")
    now = _utc(now_text)
    if abs((datetime.now(timezone.utc) - now).total_seconds()) > 86400:
        raise ValueError("retention clock differs from system UTC by more than 24 hours")
    valid: list[tuple[datetime, Path, dict[str, Any]]] = []
    for child in sorted(repository.iterdir()):
        if child.is_dir() and BACKUP_ID.fullmatch(child.name):
            try:
                manifest = load_manifest(child / "manifest.json", verify_files=True)
                valid.append((_utc(manifest["createdAt"]), child, manifest))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    valid.sort(reverse=True)
    if len(valid) < minimum_count:
        raise ValueError("fewer than the required minimum valid backups")
    cutoff = now - timedelta(days=minimum_days)
    keep = {path for _, path, _ in valid[:minimum_count]}
    delete = [path for created, path, _ in valid if created < cutoff and path not in keep]
    state = [
        {"path": str(path), "manifestSha256": digest(path / "manifest.json")}
        for _, path, _ in valid
    ]
    body = {
        "now": now_text,
        "minimumDays": minimum_days,
        "minimumCount": minimum_count,
        "state": state,
        "delete": [str(path) for path in delete],
    }
    plan_id = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {"planId": plan_id, **body}


def pitr_config(target_time: str, restore_command: str, action: str) -> str:
    _utc(target_time)
    if action not in {"promote", "pause", "shutdown"}:
        raise ValueError("invalid recovery action")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", restore_command):
        raise ValueError("restore command must be an absolute shell-safe path")
    postgres_time = target_time.removesuffix("Z").replace("T", " ") + "+00"
    return (
        "\n".join(
            (
                f"restore_command = '{restore_command} %f %p'",
                f"recovery_target_time = '{postgres_time}'",
                "recovery_target_timeline = 'latest'",
                "recovery_target_inclusive = true",
                f"recovery_target_action = '{action}'",
            )
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--verify-files", action="store_true")
    schema = sub.add_parser("schema-validate")
    schema.add_argument("manifest", type=Path)
    schema.add_argument("schema", type=Path)
    retention = sub.add_parser("retention-plan")
    retention.add_argument("--repository", required=True, type=Path)
    retention.add_argument("--now", required=True)
    retention.add_argument("--minimum-days", type=int, default=35)
    retention.add_argument("--minimum-count", type=int, default=2)
    pitr = sub.add_parser("pitr-config")
    pitr.add_argument("--target-time", required=True)
    pitr.add_argument("--restore-command", required=True)
    pitr.add_argument("--action", default="promote")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            load_manifest(args.manifest, args.verify_files)
            print(f"valid manifest: {args.manifest}")
        elif args.command == "schema-validate":
            schema_validate(args.manifest, args.schema)
            print(f"schema-valid manifest: {args.manifest}")
        elif args.command == "retention-plan":
            print(
                json.dumps(
                    retention_plan(
                        args.repository, args.now, args.minimum_days, args.minimum_count
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(pitr_config(args.target_time, args.restore_command, args.action), end="")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"backup manifest error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
