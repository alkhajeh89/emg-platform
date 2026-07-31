#!/usr/bin/env python3
"""Generate a deterministic CycloneDX SBOM from the reviewed production lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path

import tomli

_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\s\\\\]+)")


def generate(
    lock_path: Path, *, repository_root: Path | None = None, version: str = "development"
) -> dict[str, object]:
    lock_bytes = lock_path.read_bytes()
    components: list[dict[str, object]] = []
    for line in lock_bytes.decode("utf-8").splitlines():
        match = _PIN.match(line)
        if not match:
            continue
        name, version = match.groups()
        normalized = name.lower().replace("_", "-")
        components.append(
            {
                "type": "library",
                "name": normalized,
                "version": version,
                "purl": f"pkg:pypi/{normalized}@{version}",
            }
        )
    if repository_root is not None:
        manifests = sorted(repository_root.glob("libs/python/*/pyproject.toml"))
        manifests += sorted(repository_root.glob("services/*/pyproject.toml"))
        for manifest in manifests:
            if not manifest.read_text(encoding="utf-8").strip():
                continue
            project = tomli.loads(manifest.read_text(encoding="utf-8")).get("project", {})
            name = project.get("name")
            component_version = project.get("version")
            if isinstance(name, str) and isinstance(component_version, str):
                components.append(
                    {
                        "type": "library",
                        "name": name,
                        "version": component_version,
                        "purl": f"pkg:pypi/{name}@{component_version}",
                    }
                )
    components.sort(key=lambda component: str(component["purl"]))
    digest = hashlib.sha256(
        lock_bytes
        + version.encode()
        + "\n".join(str(component["purl"]) for component in components).encode()
    ).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, digest)}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "emg-platform",
                "version": version,
            },
            "properties": [{"name": "emg:production-lock-sha256", "value": digest}],
        },
        "components": components,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=Path("requirements-production.lock"))
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--version", default="development")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = generate(args.lock, repository_root=args.repository_root, version=args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
