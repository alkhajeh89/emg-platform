#!/usr/bin/env python3
"""Generate and validate ADR-040 runtime-image release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
GOVERNED_IMAGE_TYPES = frozenset({"service", "deployment-tool"})
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IMMUTABLE_IMAGE_PATTERN = re.compile(
    r"^ghcr\.io/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?/emg-platform/"
    r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?@sha256:[0-9a-f]{64}$"
)
MIGRATION_ROOT = ROOT / "libs/python/emg-persistence/src/emg_persistence/migrations"


class ReleaseValidationError(ValueError):
    """A finalized runtime-image release violates ADR-040."""


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def governed_images(manifest_path: Path | None = None) -> list[dict[str, str]]:
    """Return the canonical EMG-built release inventory in stable order."""
    path = manifest_path or ROOT / "docker/dependencies.yaml"
    payload = _load_yaml(path)
    services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(services, dict):
        raise ReleaseValidationError("dependency manifest is missing services")

    images: list[dict[str, str]] = []
    for name, component in services.items():
        if not isinstance(component, dict) or component.get("type") not in GOVERNED_IMAGE_TYPES:
            continue
        dockerfile = component.get("dockerfile")
        component_path = component.get("path")
        if not isinstance(name, str) or not isinstance(dockerfile, str):
            raise ReleaseValidationError("governed image registration is incomplete")
        if not isinstance(component_path, str):
            raise ReleaseValidationError(f"{name}: governed image path is missing")
        if manifest_path is None and not (ROOT / dockerfile).is_file():
            raise ReleaseValidationError(f"{name}: Dockerfile does not exist: {dockerfile}")
        images.append(
            {
                "service": name,
                "component_type": str(component["type"]),
                "path": component_path,
                "dockerfile": dockerfile,
                "ownership": "emg-built",
            }
        )
    return sorted(images, key=lambda image: image["service"])


def github_matrix(manifest_path: Path | None = None) -> dict[str, list[dict[str, str]]]:
    return {"include": governed_images(manifest_path)}


def canonical_repository(owner: str, service: str) -> str:
    normalized_owner = owner.strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?", normalized_owner):
        raise ReleaseValidationError("invalid GHCR repository owner")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?", service):
        raise ReleaseValidationError("invalid canonical service name")
    return f"ghcr.io/{normalized_owner}/emg-platform/{service}"


def _validate_digest(digest: str) -> None:
    if not DIGEST_PATTERN.fullmatch(digest):
        raise ReleaseValidationError("image digest must be canonical sha256")
    hexadecimal = digest.removeprefix("sha256:")
    if len(set(hexadecimal)) == 1 or hexadecimal.startswith("0" * 56):
        raise ReleaseValidationError("synthetic image digest is forbidden")


def build_image_record(
    *,
    service: str,
    owner: str,
    digest: str,
    commit: str,
    source_repository: str,
    workflow_identity: str,
    workflow_run: str,
    sbom_path: Path,
    vulnerability_report_path: Path,
    provenance_reference: str,
) -> dict[str, Any]:
    inventory = {image["service"]: image for image in governed_images()}
    if service not in inventory:
        raise ReleaseValidationError(f"unknown governed image: {service}")
    _validate_digest(digest)
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ReleaseValidationError("source commit must be a full lowercase Git SHA")
    repository = canonical_repository(owner, service)
    sbom_payload = _load_yaml(sbom_path)
    if not isinstance(sbom_payload, dict) or sbom_payload.get("bomFormat") != "CycloneDX":
        raise ReleaseValidationError(f"{service}: SBOM is not CycloneDX")
    sbom_sha256 = hashlib.sha256(sbom_path.read_bytes()).hexdigest()
    vulnerability_payload = json.loads(vulnerability_report_path.read_text(encoding="utf-8"))
    runs = vulnerability_payload.get("runs") if isinstance(vulnerability_payload, dict) else None
    if not isinstance(runs, list) or any(run.get("results") for run in runs):
        raise ReleaseValidationError(f"{service}: blocking vulnerability report did not pass")
    vulnerability_sha256 = hashlib.sha256(vulnerability_report_path.read_bytes()).hexdigest()
    image_reference = f"{repository}@{digest}"
    return {
        "service": service,
        "componentType": inventory[service]["component_type"],
        "ownership": "emg-built",
        "imageRepository": repository,
        "digest": digest,
        "imageReference": image_reference,
        "source": {
            "repository": source_repository,
            "commit": commit,
            "workflowIdentity": workflow_identity,
            "workflowRun": workflow_run,
        },
        "sbom": {
            "format": "CycloneDX",
            "path": f"sboms/{service}.cdx.json",
            "sha256": sbom_sha256,
        },
        "vulnerability": {
            "scanner": "trivy",
            "status": "passed",
            "blockingSeverity": "CRITICAL",
            "ignoreUnfixed": True,
            "path": f"scans/{service}.trivy.sarif",
            "sha256": vulnerability_sha256,
        },
        "signature": {
            "type": "cosign-keyless",
            "status": "verified",
            "subject": image_reference,
        },
        "provenance": {
            "type": "github-artifact-attestation",
            "status": "attested",
            "subject": image_reference,
            "reference": provenance_reference,
        },
    }


def _validate_record(record: dict[str, Any], expected: dict[str, dict[str, str]]) -> None:
    service = record.get("service")
    if not isinstance(service, str) or service not in expected:
        raise ReleaseValidationError(f"unknown release image: {service}")
    if record.get("ownership") != "emg-built":
        raise ReleaseValidationError(f"{service}: ownership must be emg-built")
    digest = record.get("digest")
    if not isinstance(digest, str):
        raise ReleaseValidationError(f"{service}: digest is missing")
    _validate_digest(digest)
    repository = record.get("imageRepository")
    reference = record.get("imageReference")
    if not isinstance(repository, str) or reference != f"{repository}@{digest}":
        raise ReleaseValidationError(f"{service}: immutable image reference is inconsistent")
    if not isinstance(reference, str) or not IMMUTABLE_IMAGE_PATTERN.fullmatch(reference):
        raise ReleaseValidationError(f"{service}: image reference is not canonical GHCR digest")
    source = record.get("source")
    if not isinstance(source, dict) or not COMMIT_PATTERN.fullmatch(str(source.get("commit", ""))):
        raise ReleaseValidationError(f"{service}: source commit is invalid")
    source_repository = source.get("repository")
    if not isinstance(source_repository, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source_repository
    ):
        raise ReleaseValidationError(f"{service}: source repository is invalid")
    if repository != canonical_repository(source_repository.split("/", maxsplit=1)[0], service):
        raise ReleaseValidationError(f"{service}: GHCR repository differs from source owner")
    workflow_identity = source.get("workflowIdentity")
    if not isinstance(workflow_identity, str) or not re.fullmatch(
        r"\.github/workflows/runtime-image-release\.yml@refs/tags/v[^\s]+",
        workflow_identity,
    ):
        raise ReleaseValidationError(f"{service}: trusted workflow identity is invalid")
    workflow_run = source.get("workflowRun")
    if not isinstance(workflow_run, str) or not re.fullmatch(
        rf"https://github\.com/{re.escape(source_repository)}/actions/runs/[0-9]+",
        workflow_run,
    ):
        raise ReleaseValidationError(f"{service}: workflow run reference is invalid")
    sbom = record.get("sbom")
    if not isinstance(sbom, dict) or sbom.get("format") != "CycloneDX":
        raise ReleaseValidationError(f"{service}: CycloneDX SBOM evidence is missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(sbom.get("sha256", ""))):
        raise ReleaseValidationError(f"{service}: SBOM checksum is invalid")
    vulnerability = record.get("vulnerability")
    if not isinstance(vulnerability, dict) or any(
        vulnerability.get(key) != value
        for key, value in {
            "scanner": "trivy",
            "status": "passed",
            "blockingSeverity": "CRITICAL",
            "ignoreUnfixed": True,
        }.items()
    ):
        raise ReleaseValidationError(f"{service}: blocking vulnerability evidence is missing")
    if vulnerability.get("path") != f"scans/{service}.trivy.sarif" or not re.fullmatch(
        r"[0-9a-f]{64}", str(vulnerability.get("sha256", ""))
    ):
        raise ReleaseValidationError(f"{service}: vulnerability report identity is invalid")
    signature = record.get("signature")
    if not isinstance(signature, dict) or (
        signature.get("type"),
        signature.get("status"),
        signature.get("subject"),
    ) != ("cosign-keyless", "verified", reference):
        raise ReleaseValidationError(f"{service}: verified keyless signature is missing")
    provenance = record.get("provenance")
    if not isinstance(provenance, dict) or (
        provenance.get("type"),
        provenance.get("status"),
        provenance.get("subject"),
    ) != ("github-artifact-attestation", "attested", reference):
        raise ReleaseValidationError(f"{service}: runtime attestation is missing")
    if provenance.get("reference") != f"https://github.com/{source_repository}/attestations":
        raise ReleaseValidationError(f"{service}: attestation reference is invalid")


def load_complete_records(records_directory: Path) -> list[dict[str, Any]]:
    expected = {image["service"]: image for image in governed_images()}
    records: list[dict[str, Any]] = []
    for path in sorted(records_directory.rglob("*.image.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ReleaseValidationError(f"invalid image record: {path}")
        _validate_record(record, expected)
        service = str(record["service"])
        sbom_matches = sorted(records_directory.rglob(f"{service}.cdx.json"))
        if len(sbom_matches) != 1:
            raise ReleaseValidationError(f"{service}: exactly one retained SBOM is required")
        sbom_path = sbom_matches[0]
        sbom_payload = _load_yaml(sbom_path)
        if not isinstance(sbom_payload, dict) or sbom_payload.get("bomFormat") != "CycloneDX":
            raise ReleaseValidationError(f"{service}: retained SBOM is not CycloneDX")
        retained_checksum = hashlib.sha256(sbom_path.read_bytes()).hexdigest()
        if retained_checksum != record["sbom"]["sha256"]:
            raise ReleaseValidationError(f"{service}: retained SBOM checksum differs")
        scan_matches = sorted(records_directory.rglob(f"{service}.trivy.sarif"))
        if len(scan_matches) != 1:
            raise ReleaseValidationError(f"{service}: exactly one Trivy report is required")
        scan_path = scan_matches[0]
        if hashlib.sha256(scan_path.read_bytes()).hexdigest() != record["vulnerability"]["sha256"]:
            raise ReleaseValidationError(f"{service}: retained Trivy report checksum differs")
        scan_payload = json.loads(scan_path.read_text(encoding="utf-8"))
        if any(run.get("results") for run in scan_payload.get("runs", [])):
            raise ReleaseValidationError(f"{service}: retained Trivy report contains findings")
        records.append(record)
    actual_names = [str(record["service"]) for record in records]
    if len(actual_names) != len(set(actual_names)):
        raise ReleaseValidationError("duplicate release image records")
    missing = sorted(set(expected) - set(actual_names))
    unknown = sorted(set(actual_names) - set(expected))
    if missing or unknown:
        raise ReleaseValidationError(
            f"release image set is incomplete (missing={missing}, unknown={unknown})"
        )
    return sorted(records, key=lambda record: str(record["service"]))


def release_manifest(
    records: list[dict[str, Any]], *, version: str, commit: str, repository: str
) -> dict[str, Any]:
    if not version.startswith("v"):
        raise ReleaseValidationError("release version must use the approved v* boundary")
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ReleaseValidationError("release commit must be a full lowercase Git SHA")
    expected = {image["service"]: image for image in governed_images()}
    for record in records:
        _validate_record(record, expected)
        if record["source"]["commit"] != commit:
            raise ReleaseValidationError(f"{record['service']}: source commit differs from release")
        if record["source"]["repository"] != repository:
            raise ReleaseValidationError(
                f"{record['service']}: source repository differs from release"
            )
    names = [str(record["service"]) for record in records]
    if len(names) != len(set(names)) or set(names) != set(expected):
        raise ReleaseValidationError("release manifest does not contain the complete image set")
    mapping = {str(record["service"]): str(record["imageReference"]) for record in records}
    migration_files = sorted(
        path
        for path in MIGRATION_ROOT.rglob("*")
        if path.is_file() and path.suffix in {".sql", ".cypher"}
    )
    migration_body = b"".join(
        path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0"
        for path in migration_files
    )
    return {
        "schemaVersion": 2,
        "release": {"version": version, "sourceRepository": repository, "commit": commit},
        "images": sorted(records, key=lambda record: str(record["service"])),
        "compatibility": {
            "migrationPolicy": "forward-only",
            "schemaRollbackAuthorized": False,
            "migrationSetSha256": hashlib.sha256(migration_body).hexdigest(),
            "migrationFiles": [path.relative_to(ROOT).as_posix() for path in migration_files],
        },
        "rollback": {"completeImageSet": dict(sorted(mapping.items()))},
    }


def _replace_images(value: Any, references: dict[str, str], used: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "image" and isinstance(child, str):
                name = child.split("@", maxsplit=1)[0].rsplit("/", maxsplit=1)[-1]
                if name not in references:
                    raise ReleaseValidationError(f"undeclared deployment image: {child}")
                value[key] = references[name]
                used.add(name)
            else:
                _replace_images(child, references, used)
    elif isinstance(value, list):
        for child in value:
            _replace_images(child, references, used)


def resolved_bundle(source_bundle: Path, manifest: dict[str, Any]) -> str:
    images = manifest.get("images")
    if not isinstance(images, list):
        raise ReleaseValidationError("release manifest images are missing")
    references = {str(image["service"]): str(image["imageReference"]) for image in images}
    documents = [document for document in yaml.safe_load_all(source_bundle.read_text()) if document]
    used: set[str] = set()
    for document in documents:
        _replace_images(document, references, used)
    missing = sorted(set(references) - used)
    if missing:
        raise ReleaseValidationError(f"release images absent from deployment bundle: {missing}")
    rendered = yaml.safe_dump_all(documents, sort_keys=False)
    validate_finalized_bundle(rendered, set(references))
    return rendered


def validate_finalized_bundle(rendered: str, expected_services: set[str]) -> None:
    lowered = rendered.lower()
    if "registry.invalid" in lowered:
        raise ReleaseValidationError("finalized bundle contains registry.invalid")
    documents = [document for document in yaml.safe_load_all(rendered) if document]
    found: set[str] = set()

    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "image" and isinstance(child, str):
                    if not IMMUTABLE_IMAGE_PATTERN.fullmatch(child):
                        raise ReleaseValidationError(f"mutable or noncanonical image: {child}")
                    service = child.split("@", maxsplit=1)[0].rsplit("/", maxsplit=1)[-1]
                    digest = child.rsplit("@", maxsplit=1)[-1]
                    _validate_digest(digest)
                    found.add(service)
                else:
                    inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    for document in documents:
        inspect(document)
    if found != expected_services:
        raise ReleaseValidationError(
            f"finalized deployment image coverage differs (expected={sorted(expected_services)}, "
            f"found={sorted(found)})"
        )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _inventory_command(args: argparse.Namespace) -> int:
    compact = json.dumps(github_matrix(), separators=(",", ":"), sort_keys=True)
    print(f"matrix={compact}" if args.github_output else compact)
    return 0


def _record_command(args: argparse.Namespace) -> int:
    record = build_image_record(
        service=args.service,
        owner=args.owner,
        digest=args.digest,
        commit=args.commit,
        source_repository=args.repository,
        workflow_identity=args.workflow_identity,
        workflow_run=args.workflow_run,
        sbom_path=args.sbom,
        vulnerability_report_path=args.vulnerability_report,
        provenance_reference=args.provenance_reference,
    )
    _write_json(args.output, record)
    return 0


def _finalize_command(args: argparse.Namespace) -> int:
    records = load_complete_records(args.records)
    manifest = release_manifest(
        records, version=args.version, commit=args.commit, repository=args.repository
    )
    bundle = resolved_bundle(args.source_bundle, manifest)
    staging_bundle = (
        resolved_bundle(args.staging_source_bundle, manifest)
        if args.staging_source_bundle is not None
        else None
    )
    manifest["configuration"] = {
        "sourceBundleSha256": {
            "production": hashlib.sha256(args.source_bundle.read_bytes()).hexdigest(),
            **(
                {"staging": hashlib.sha256(args.staging_source_bundle.read_bytes()).hexdigest()}
                if args.staging_source_bundle is not None
                else {}
            ),
        },
        "resolvedBundleSha256": {
            "production": hashlib.sha256(bundle.encode()).hexdigest(),
            **(
                {"staging": hashlib.sha256(staging_bundle.encode()).hexdigest()}
                if staging_bundle is not None
                else {}
            ),
        },
    }
    _write_json(args.manifest_output, manifest)
    args.bundle_output.parent.mkdir(parents=True, exist_ok=True)
    args.bundle_output.write_text(bundle, encoding="utf-8")
    if staging_bundle is not None:
        if args.staging_bundle_output is None:
            raise ReleaseValidationError("staging bundle output is required")
        args.staging_bundle_output.parent.mkdir(parents=True, exist_ok=True)
        args.staging_bundle_output.write_text(staging_bundle, encoding="utf-8")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("--github-output", action="store_true")
    inventory.set_defaults(handler=_inventory_command)

    record = commands.add_parser("record")
    record.add_argument("--service", required=True)
    record.add_argument("--owner", required=True)
    record.add_argument("--digest", required=True)
    record.add_argument("--commit", required=True)
    record.add_argument("--repository", required=True)
    record.add_argument("--workflow-identity", required=True)
    record.add_argument("--workflow-run", required=True)
    record.add_argument("--sbom", type=Path, required=True)
    record.add_argument("--vulnerability-report", type=Path, required=True)
    record.add_argument("--provenance-reference", required=True)
    record.add_argument("--output", type=Path, required=True)
    record.set_defaults(handler=_record_command)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--records", type=Path, required=True)
    finalize.add_argument("--version", required=True)
    finalize.add_argument("--commit", required=True)
    finalize.add_argument("--repository", required=True)
    finalize.add_argument("--source-bundle", type=Path, required=True)
    finalize.add_argument("--staging-source-bundle", type=Path)
    finalize.add_argument("--manifest-output", type=Path, required=True)
    finalize.add_argument("--bundle-output", type=Path, required=True)
    finalize.add_argument("--staging-bundle-output", type=Path)
    finalize.set_defaults(handler=_finalize_command)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
