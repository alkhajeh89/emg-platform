#!/usr/bin/env python3
"""Fail-closed RC-D release, staging, promotion, and rollback qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from runtime_image_release import (
    ReleaseValidationError,
    governed_images,
    release_manifest,
    validate_finalized_bundle,
)


class QualificationError(ValueError):
    """Release evidence is incomplete, mixed, mutable, or unqualified."""


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise QualificationError(f"JSON object required: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_manifest(manifest: dict[str, Any], sbom_directory: Path) -> set[str]:
    if manifest.get("schemaVersion") != 2:
        raise QualificationError("release manifest schemaVersion 2 is required")
    release = manifest.get("release")
    images = manifest.get("images")
    if not isinstance(release, dict) or not isinstance(images, list):
        raise QualificationError("release identity or image set is missing")
    try:
        reconstructed = release_manifest(
            images,
            version=str(release.get("version", "")),
            commit=str(release.get("commit", "")),
            repository=str(release.get("sourceRepository", "")),
        )
    except ReleaseValidationError as exc:
        raise QualificationError(str(exc)) from exc
    for key in ("release", "images", "compatibility", "rollback"):
        if manifest.get(key) != reconstructed[key]:
            raise QualificationError(f"release manifest {key} differs from canonical evidence")
    configuration = manifest.get("configuration")
    if not isinstance(configuration, dict) or not all(
        isinstance(configuration.get(field), expected_type)
        for field, expected_type in (
            ("sourceBundleSha256", dict),
            ("resolvedBundleSha256", dict),
        )
    ):
        raise QualificationError("source deployment configuration identity is missing")
    for mapping_name in ("sourceBundleSha256", "resolvedBundleSha256"):
        mapping = configuration[mapping_name]
        if not mapping or any(
            key not in {"staging", "production"}
            or not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for key, value in mapping.items()
        ):
            raise QualificationError(f"invalid {mapping_name} configuration identity")
    services = {str(image["service"]) for image in images}
    expected = {image["service"] for image in governed_images()}
    if services != expected:
        raise QualificationError("release image set is incomplete")
    for image in images:
        service = str(image["service"])
        sbom = sbom_directory / f"{service}.cdx.json"
        if not sbom.is_file() or _sha256(sbom) != image["sbom"]["sha256"]:
            raise QualificationError(f"{service}: retained SBOM is missing or changed")
        payload = _json(sbom)
        if payload.get("bomFormat") != "CycloneDX":
            raise QualificationError(f"{service}: retained SBOM is not CycloneDX")
        scan = sbom_directory.parent / "scans" / f"{service}.trivy.sarif"
        if not scan.is_file() or _sha256(scan) != image["vulnerability"]["sha256"]:
            raise QualificationError(f"{service}: retained Trivy report is missing or changed")
        scan_payload = _json(scan)
        if any(run.get("results") for run in scan_payload.get("runs", [])):
            raise QualificationError(f"{service}: blocking vulnerability report contains findings")
    return services


def repository_qualification(
    manifest_path: Path,
    bundle_path: Path,
    sbom_directory: Path,
    environment: str,
) -> dict[str, Any]:
    if environment not in {"staging", "production"}:
        raise QualificationError("qualification environment must be staging or production")
    manifest = _json(manifest_path)
    services = _validate_manifest(manifest, sbom_directory)
    if manifest["configuration"]["resolvedBundleSha256"].get(environment) != _sha256(bundle_path):
        raise QualificationError("resolved bundle differs from the release configuration identity")
    bundle = bundle_path.read_text(encoding="utf-8")
    try:
        validate_finalized_bundle(bundle, services)
    except ReleaseValidationError as exc:
        raise QualificationError(str(exc)) from exc
    objects = [item for item in yaml.safe_load_all(bundle) if item]
    if any(item.get("kind") == "Secret" for item in objects):
        raise QualificationError("literal Kubernetes Secret is forbidden in release evidence")
    namespaces = {
        item.get("metadata", {}).get("namespace")
        for item in objects
        if item.get("kind") != "Namespace"
    }
    expected_namespace = f"emg-{environment}"
    if namespaces != {expected_namespace}:
        raise QualificationError("resolved bundle targets the wrong environment namespace")
    staged = {
        item.get("metadata", {})
        .get("name"): item.get("metadata", {})
        .get("annotations", {})
        .get("emg.platform/bootstrap-stage")
        for item in objects
    }
    required_stages = {
        "emg-database-bootstrap": "10-database-roles",
        "emg-audit-migration": "20-postgresql-migrations",
        "emg-knowledge-graph-migration": "20-postgresql-migrations",
        "emg-keycloak-provision": "30-keycloak-projector-clients",
        "emg-provisioning-validate": "50-consistency-validation",
        "emg-audit": "60-audit-service",
        "emg-audit-projector": "70-audit-projector",
    }
    if any(staged.get(name) != stage for name, stage in required_stages.items()):
        raise QualificationError("governed provisioning/deployment stage order is incomplete")
    kinds = {(item.get("kind"), item.get("metadata", {}).get("name")) for item in objects}
    if ("CronJob", "emg-postgresql-backup") not in kinds:
        raise QualificationError("recovery workload is absent from the qualified bundle")
    identity = manifest["release"]
    return {
        "schemaVersion": 1,
        "release": identity,
        "releaseManifestSha256": _sha256(manifest_path),
        "resolvedBundleSha256": _sha256(bundle_path),
        "environment": environment,
        "checks": {
            "completeImmutableImageSet": "PASS",
            "blockingVulnerabilityPolicy": "PASS",
            "cycloneDxSboms": "PASS",
            "signatures": "PASS",
            "provenance": "PASS",
            "migrationContract": "PASS",
            "manifestRender": "PASS",
            "literalSecretAbsence": "PASS",
            "deploymentOrder": "PASS",
            "recoveryWorkload": "PASS",
        },
        "stagingDeployment": "PENDING",
        "smokeTests": "PENDING",
        "rollbackRehearsal": "PENDING",
        "productionPromotion": "BLOCKED",
        "result": "REPOSITORY_VALIDATED_LIVE_QUALIFICATION_PENDING",
    }


def promotion_gate(evidence_path: Path, manifest_path: Path) -> None:
    evidence = _json(evidence_path)
    manifest = _json(manifest_path)
    if evidence.get("releaseManifestSha256") != _sha256(manifest_path):
        raise QualificationError("qualification evidence belongs to a different release manifest")
    if (
        evidence.get("release") != manifest.get("release")
        or evidence.get("environment") != "staging"
    ):
        raise QualificationError("qualification evidence identity is not the staging release")
    if evidence.get("result") != "WITNESSED_STAGING_QUALIFIED":
        raise QualificationError("production promotion blocked: staging result is not witnessed")
    checks = evidence.get("checks")
    if not isinstance(checks, dict) or any(value != "PASS" for value in checks.values()):
        raise QualificationError("production promotion blocked: a qualification check did not pass")
    witness = evidence.get("witness")
    if not isinstance(witness, dict) or witness.get("approvalBoundary") != (
        "github-actions-protected-environment"
    ):
        raise QualificationError("protected staging witness evidence is missing")
    workflow = witness.get("workflowIdentity")
    run = witness.get("workflowRun")
    repository = re.escape(str(manifest["release"].get("sourceRepository", "")))
    if not isinstance(workflow, str) or not re.fullmatch(
        r"\.github/workflows/[a-z0-9._-]+\.yml@refs/tags/v[^\s]+", workflow
    ):
        raise QualificationError("staging witness workflow identity is invalid")
    if not isinstance(run, str) or not re.fullmatch(
        rf"https://github\.com/{repository}/actions/runs/[0-9]+", run
    ):
        raise QualificationError("staging witness run identity is invalid")
    required = {
        "stagingDeployment": "PASS",
        "smokeTests": "PASS",
        "rollbackRehearsal": "PASS",
    }
    for field, expected in required.items():
        if evidence.get(field) != expected:
            raise QualificationError(f"production promotion blocked: {field} is not {expected}")


def rollback_gate(current_path: Path, previous_path: Path) -> None:
    current = _json(current_path)
    previous = _json(previous_path)
    current_services = _validate_manifest(current, current_path.parent / "sboms")
    previous_services = _validate_manifest(previous, previous_path.parent / "sboms")
    if current_services != previous_services:
        raise QualificationError("rollback release sets differ")
    if current["release"] == previous["release"]:
        raise QualificationError("rollback candidate must be a prior distinct release")
    if (
        current["compatibility"]["migrationSetSha256"]
        != previous["compatibility"]["migrationSetSha256"]
    ):
        raise QualificationError(
            "database migration sets differ; schema rollback is forbidden and forward-fix "
            "compatibility requires separate qualification"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    qualify = commands.add_parser("repository-qualify")
    qualify.add_argument("--manifest", required=True, type=Path)
    qualify.add_argument("--bundle", required=True, type=Path)
    qualify.add_argument("--sbom-directory", required=True, type=Path)
    qualify.add_argument("--environment", required=True, choices=("staging", "production"))
    qualify.add_argument("--output", required=True, type=Path)
    promotion = commands.add_parser("promotion-gate")
    promotion.add_argument("--evidence", required=True, type=Path)
    promotion.add_argument("--manifest", required=True, type=Path)
    rollback = commands.add_parser("rollback-gate")
    rollback.add_argument("--current", required=True, type=Path)
    rollback.add_argument("--previous", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "repository-qualify":
            evidence = repository_qualification(
                args.manifest, args.bundle, args.sbom_directory, args.environment
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        elif args.command == "promotion-gate":
            promotion_gate(args.evidence, args.manifest)
        else:
            rollback_gate(args.current, args.previous)
    except (OSError, json.JSONDecodeError, QualificationError) as exc:
        print(f"release qualification failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
