from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/ci"))

from release_qualification import (  # noqa: E402
    QualificationError,
    promotion_gate,
    repository_qualification,
    rollback_gate,
)
from runtime_image_release import (  # noqa: E402
    ReleaseValidationError,
    build_image_record,
    governed_images,
    load_complete_records,
    release_manifest,
    resolved_bundle,
    validate_finalized_bundle,
)

WORKFLOW_PATH = ROOT / ".github/workflows/runtime-image-release.yml"
COMMIT = "1a" * 20
SOURCE_REPOSITORY = "emg/example"
EXPECTED_APPLICATION_IMAGES = {
    "studio",
    "identity",
    "audit",
    "audit-projector",
    "knowledge-graph",
    "studio-bff",
}
EXPECTED_RELEASE_IMAGES = EXPECTED_APPLICATION_IMAGES | {"keycloak-provisioner", "recovery-tool"}


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _trigger(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML 1.1 reads the unquoted GitHub Actions `on` key as boolean true.
    return workflow.get("on", workflow.get(True, {}))


def _all_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def _records(tmp_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    directory = tmp_path / "records"
    directory.mkdir(parents=True)
    sbom_directory = directory / "sboms"
    scan_directory = directory / "scans"
    sbom_directory.mkdir()
    scan_directory.mkdir()
    records: list[dict[str, Any]] = []
    for image in governed_images():
        service = image["service"]
        sbom = sbom_directory / f"{service}.cdx.json"
        sbom.write_text(
            json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5"}) + "\n",
            encoding="utf-8",
        )
        scan = scan_directory / f"{service}.trivy.sarif"
        scan.write_text(json.dumps({"version": "2.1.0", "runs": [{"results": []}]}))
        digest = "sha256:" + hashlib.sha256(service.encode()).hexdigest()
        record = build_image_record(
            service=service,
            owner="emg",
            digest=digest,
            commit=COMMIT,
            source_repository=SOURCE_REPOSITORY,
            workflow_identity=".github/workflows/runtime-image-release.yml@refs/tags/v1.0.0",
            workflow_run="https://github.com/emg/example/actions/runs/1",
            sbom_path=sbom,
            vulnerability_report_path=scan,
            provenance_reference="https://github.com/emg/example/attestations",
        )
        (directory / f"{service}.image.json").write_text(json.dumps(record), encoding="utf-8")
        records.append(record)
    return directory, records


def _source_bundle() -> str:
    documents = []
    for index, service in enumerate(sorted(EXPECTED_RELEASE_IMAGES), start=1):
        documents.append(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": service},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": service,
                                    "image": "registry.invalid/emg/"
                                    f"{service}@sha256:{index:064x}",
                                }
                            ]
                        }
                    }
                },
            }
        )
    return yaml.safe_dump_all(documents, sort_keys=False)


def test_canonical_inventory_governs_applications_and_deployment_tools() -> None:
    inventory = {image["service"]: image for image in governed_images()}

    assert set(inventory) == EXPECTED_RELEASE_IMAGES
    assert {
        service for service, image in inventory.items() if image["component_type"] == "service"
    } == EXPECTED_APPLICATION_IMAGES
    provisioner = inventory["keycloak-provisioner"]
    assert provisioner["component_type"] == "deployment-tool"
    assert provisioner["dockerfile"] == "tools/keycloak-provisioner.Dockerfile"
    dockerfile = (ROOT / provisioner["dockerfile"]).read_text(encoding="utf-8")
    assert "tools/scripts/provision-keycloak-realm.py" in dockerfile
    assert "ENTRYPOINT" in dockerfile
    recovery = inventory["recovery-tool"]
    assert recovery["component_type"] == "deployment-tool"
    assert recovery["dockerfile"] == "tools/recovery.Dockerfile"
    recovery_dockerfile = (ROOT / recovery["dockerfile"]).read_text(encoding="utf-8")
    assert "USER 10001:10001" in recovery_dockerfile
    assert "scheduled-backup.sh" in recovery_dockerfile


def test_studio_image_is_standalone_non_root_and_uses_only_internal_bff() -> None:
    inventory = {image["service"]: image for image in governed_images()}
    assert inventory["studio"]["dockerfile"] == "apps/studio/Dockerfile"
    dockerfile = (ROOT / "apps/studio/Dockerfile").read_text(encoding="utf-8")
    next_config = (ROOT / "apps/studio/next.config.ts").read_text(encoding="utf-8")
    assert 'output: "standalone"' in next_config
    assert "npm ci --workspace @emg/studio" in dockerfile
    assert "STUDIO_BFF_INTERNAL_URL=http://emg-studio-bff:8000" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "next dev" not in dockerfile
    assert "KNOWLEDGE_GRAPH" not in dockerfile


def test_release_workflow_has_only_the_trusted_tag_trigger_and_environment() -> None:
    workflow = _workflow()
    trigger = _trigger(workflow)
    privileged = workflow["jobs"]["publish-sign-attest"]

    assert trigger == {"push": {"tags": ["v*"]}}
    assert "pull_request" not in trigger
    assert "workflow_dispatch" not in trigger
    assert workflow["permissions"] == {"contents": "read"}
    assert privileged["environment"] == "production-release"
    assert privileged["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }
    assert workflow["jobs"]["build-scan"]["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["finalize-release"]["permissions"] == {"contents": "read"}


def test_workflow_builds_once_and_scan_blocks_publication() -> None:
    workflow = _workflow()
    build = workflow["jobs"]["build-scan"]
    release = workflow["jobs"]["publish-sign-attest"]
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    scan = next(step for step in build["steps"] if step["name"] == "Mandatory Trivy security gate")

    assert workflow_text.count("docker build --pull=false") == 1
    assert "build-scan" in release["needs"]
    assert scan["with"]["severity"] == "CRITICAL"
    assert scan["with"]["ignore-unfixed"] is True
    assert scan["with"]["exit-code"] == "1"
    assert "continue-on-error" not in scan
    publish = next(
        step
        for step in release["steps"]
        if step["name"] == "Publish the scanned image and capture its digest"
    )
    assert "docker load" in publish["run"]
    assert "docker push" in publish["run"]
    assert re.search(r"docker build(?:\s|$)", publish["run"]) is None
    assert "^sha256:[0-9a-f]{64}$" in publish["run"]


def test_audit_projector_image_is_smoked_before_scan_and_publication() -> None:
    workflow = _workflow()
    build_steps = workflow["jobs"]["build-scan"]["steps"]
    names = [step["name"] for step in build_steps]
    smoke = next(
        step
        for step in build_steps
        if step["name"] == "Smoke audit-projector runtime and provisioning entrypoints"
    )

    assert names.index(smoke["name"]) < names.index("Mandatory Trivy security gate")
    assert smoke["if"] == "matrix.service == 'audit-projector'"
    assert "smoke_audit_projector_image.py" in smoke["run"]
    assert '"emg-release/audit-projector:${GITHUB_SHA}" python /smoke.py' in smoke["run"]

    smoke_script = (ROOT / "tools/ci/smoke_audit_projector_image.py").read_text(encoding="utf-8")
    assert '"EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN": "postgresql://smoke"' in smoke_script
    assert '"EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN": "postgresql://smoke"' in smoke_script
    assert "provisioning.bootstrap_database_roles = lambda" in smoke_script


def test_workflow_signs_verifies_attests_and_records_every_matrix_digest() -> None:
    workflow = _workflow()
    release = workflow["jobs"]["publish-sign-attest"]
    steps = {step["name"]: step for step in release["steps"]}

    assert "fromJSON(needs.inventory.outputs.matrix)" in release["strategy"]["matrix"]
    assert "cosign sign --yes" in steps["Sign immutable digest with keyless OIDC"]["run"]
    verify = steps["Verify the approved signing identity"]
    assert "--certificate-identity" in verify["run"]
    assert "--certificate-oidc-issuer" in verify["run"]
    assert "runtime-image-release.yml@${{ github.ref }}" in verify["env"]["EXPECTED_IDENTITY"]
    attest = steps["Attest runtime image provenance"]
    assert attest["with"]["subject-digest"] == "${{ steps.publish.outputs.digest }}"
    assert attest["with"]["push-to-registry"] is True
    record = steps["Record verified image evidence"]["run"]
    assert "--sbom" in record
    assert "--vulnerability-report" in record
    assert "--provenance-reference" in record
    assert "--digest" in record


def test_workflow_actions_are_sha_pinned_and_release_evidence_uses_default_retention() -> None:
    workflow = _workflow()
    action_reference = re.compile(r"^[^@]+@[0-9a-f]{40}$")
    for step in _all_steps(workflow):
        if "uses" in step:
            assert action_reference.fullmatch(step["uses"]), step["uses"]

    final_upload = next(
        step
        for step in workflow["jobs"]["finalize-release"]["steps"]
        if step["name"] == "Upload retained runtime release evidence"
    )
    assert "retention-days" not in final_upload["with"]
    assert final_upload["with"]["path"] == "release-evidence/"


def test_workflow_generates_staging_bundle_and_pending_qualification_evidence() -> None:
    workflow = _workflow()
    steps = {step["name"]: step for step in workflow["jobs"]["finalize-release"]["steps"]}
    render = steps["Render production source template"]["run"]
    assert "infra/environments/production" in render
    assert "infra/environments/staging" in render
    generate = steps["Generate complete manifest, deployment bundle and rollback evidence"]["run"]
    assert "--staging-source-bundle" in generate
    assert "--staging-bundle-output" in generate
    qualify = steps["Validate repository-controlled staging qualification contract"]["run"]
    assert "release_qualification.py repository-qualify" in qualify
    assert "--environment staging" in qualify
    assert "staging-qualification.json" in qualify


def test_complete_manifest_binds_all_images_and_is_rollback_complete(tmp_path: Path) -> None:
    directory, expected_records = _records(tmp_path)
    records = load_complete_records(directory)
    manifest = release_manifest(
        records, version="v1.0.0", commit=COMMIT, repository=SOURCE_REPOSITORY
    )

    assert records == sorted(expected_records, key=lambda record: record["service"])
    assert {image["service"] for image in manifest["images"]} == EXPECTED_RELEASE_IMAGES
    assert set(manifest["rollback"]["completeImageSet"]) == EXPECTED_RELEASE_IMAGES
    for image in manifest["images"]:
        assert image["imageReference"].endswith("@" + image["digest"])
        assert image["sbom"]["format"] == "CycloneDX"
        assert image["signature"]["status"] == "verified"
        assert image["provenance"]["status"] == "attested"
        assert image["vulnerability"]["status"] == "passed"
    assert manifest["schemaVersion"] == 2
    assert manifest["compatibility"]["migrationPolicy"] == "forward-only"
    assert manifest["compatibility"]["schemaRollbackAuthorized"] is False
    assert manifest["compatibility"]["migrationFiles"]


def test_missing_or_duplicate_image_record_fails_finalization(tmp_path: Path) -> None:
    directory, _ = _records(tmp_path)
    (directory / "identity.image.json").unlink()
    with pytest.raises(ReleaseValidationError, match="incomplete"):
        load_complete_records(directory)

    directory, _ = _records(tmp_path / "duplicate")
    original = directory / "identity.image.json"
    (directory / "identity-copy.image.json").write_bytes(original.read_bytes())
    with pytest.raises(ReleaseValidationError, match="duplicate"):
        load_complete_records(directory)


def test_missing_or_modified_retained_sbom_fails_finalization(tmp_path: Path) -> None:
    directory, _ = _records(tmp_path)
    (directory / "sboms/identity.cdx.json").unlink()
    with pytest.raises(ReleaseValidationError, match="retained SBOM"):
        load_complete_records(directory)


def test_missing_vulnerability_evidence_fails_finalization(tmp_path: Path) -> None:
    directory, _ = _records(tmp_path)
    record_path = directory / "identity.image.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    del record["vulnerability"]
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ReleaseValidationError, match="vulnerability evidence"):
        load_complete_records(directory)

    directory, _ = _records(tmp_path / "modified")
    (directory / "sboms/identity.cdx.json").write_text(
        '{"bomFormat":"CycloneDX","changed":true}\n', encoding="utf-8"
    )
    with pytest.raises(ReleaseValidationError, match="checksum differs"):
        load_complete_records(directory)


def test_resolved_bundle_is_immutable_complete_and_placeholder_free(tmp_path: Path) -> None:
    _, records = _records(tmp_path)
    manifest = release_manifest(
        records, version="v1.0.0", commit=COMMIT, repository=SOURCE_REPOSITORY
    )
    source = tmp_path / "production-template.yaml"
    source.write_text(_source_bundle(), encoding="utf-8")

    first = resolved_bundle(source, manifest)
    second = resolved_bundle(source, manifest)

    assert first == second
    assert "registry.invalid" not in first
    assert set(re.findall(r"ghcr\.io/[^\s]+@sha256:[0-9a-f]{64}", first))
    validate_finalized_bundle(first, EXPECTED_RELEASE_IMAGES)


def test_actual_production_overlay_resolves_every_governed_image(tmp_path: Path) -> None:
    _, records = _records(tmp_path)
    manifest = release_manifest(
        records, version="v1.0.0", commit=COMMIT, repository=SOURCE_REPOSITORY
    )
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/environments/production")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    source = tmp_path / "actual-production-template.yaml"
    source.write_text(rendered, encoding="utf-8")

    finalized = resolved_bundle(source, manifest)

    validate_finalized_bundle(finalized, EXPECTED_RELEASE_IMAGES)
    assert "registry.invalid" not in finalized


def test_staging_overlay_resolves_and_repository_evidence_blocks_promotion(
    tmp_path: Path,
) -> None:
    directory, records = _records(tmp_path)
    manifest = release_manifest(
        records, version="v1.0.0", commit=COMMIT, repository=SOURCE_REPOSITORY
    )
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/environments/staging")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    source = tmp_path / "staging-template.yaml"
    source.write_text(rendered, encoding="utf-8")
    finalized = resolved_bundle(source, manifest)
    bundle = tmp_path / "staging-resolved.yaml"
    bundle.write_text(finalized, encoding="utf-8")
    manifest["configuration"] = {
        "sourceBundleSha256": {"staging": hashlib.sha256(source.read_bytes()).hexdigest()},
        "resolvedBundleSha256": {"staging": hashlib.sha256(bundle.read_bytes()).hexdigest()},
    }
    manifest_path = tmp_path / "release-images.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    evidence = repository_qualification(manifest_path, bundle, directory / "sboms", "staging")
    assert evidence["result"] == "REPOSITORY_VALIDATED_LIVE_QUALIFICATION_PENDING"
    assert evidence["stagingDeployment"] == "PENDING"
    assert evidence["productionPromotion"] == "BLOCKED"
    evidence_path = tmp_path / "qualification.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(QualificationError, match="not witnessed"):
        promotion_gate(evidence_path, manifest_path)


def test_qualification_rejects_bundle_or_sbom_drift(tmp_path: Path) -> None:
    directory, records = _records(tmp_path)
    manifest = release_manifest(
        records, version="v1.0.0", commit=COMMIT, repository=SOURCE_REPOSITORY
    )
    source = tmp_path / "staging-template.yaml"
    source.write_text(_source_bundle(), encoding="utf-8")
    bundle = tmp_path / "staging-resolved.yaml"
    bundle.write_text(resolved_bundle(source, manifest), encoding="utf-8")
    manifest["configuration"] = {
        "sourceBundleSha256": {"staging": hashlib.sha256(source.read_bytes()).hexdigest()},
        "resolvedBundleSha256": {"staging": hashlib.sha256(bundle.read_bytes()).hexdigest()},
    }
    manifest_path = tmp_path / "release-images.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    (directory / "sboms/identity.cdx.json").write_text("{}", encoding="utf-8")
    with pytest.raises(QualificationError, match="SBOM"):
        repository_qualification(manifest_path, bundle, directory / "sboms", "staging")


def test_promotion_gate_accepts_only_witnessed_complete_exact_release(tmp_path: Path) -> None:
    manifest = tmp_path / "release-images.json"
    release = {
        "version": "v1.0.0",
        "sourceRepository": SOURCE_REPOSITORY,
        "commit": COMMIT,
    }
    manifest.write_text(json.dumps({"release": release}), encoding="utf-8")
    evidence = {
        "release": release,
        "releaseManifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "environment": "staging",
        "result": "WITNESSED_STAGING_QUALIFIED",
        "checks": {"immutableRelease": "PASS"},
        "stagingDeployment": "PASS",
        "smokeTests": "PASS",
        "rollbackRehearsal": "PASS",
        "witness": {
            "approvalBoundary": "github-actions-protected-environment",
            "workflowIdentity": ".github/workflows/staging.yml@refs/tags/v1.0.0",
            "workflowRun": "https://github.com/emg/example/actions/runs/1",
        },
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    promotion_gate(evidence_path, manifest)

    manifest.write_text('{"release":"changed"}\n', encoding="utf-8")
    with pytest.raises(QualificationError, match="different release"):
        promotion_gate(evidence_path, manifest)


def test_rollback_gate_requires_complete_distinct_migration_compatible_set(
    tmp_path: Path,
) -> None:
    current_directory, current_records = _records(tmp_path / "current")
    previous_directory, previous_records = _records(tmp_path / "previous")
    current = release_manifest(
        current_records, version="v2.0.0", commit=COMMIT, repository=SOURCE_REPOSITORY
    )
    previous = release_manifest(
        previous_records,
        version="v1.0.0",
        commit=COMMIT,
        repository=SOURCE_REPOSITORY,
    )
    configuration = {
        "sourceBundleSha256": {"production": "1" * 64},
        "resolvedBundleSha256": {"production": "2" * 64},
    }
    current["configuration"] = configuration
    previous["configuration"] = configuration
    current_path = current_directory / "release-images.json"
    previous_path = previous_directory / "release-images.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    previous_path.write_text(json.dumps(previous), encoding="utf-8")
    rollback_gate(current_path, previous_path)

    previous["images"] = previous["images"][:-1]
    previous_path.write_text(json.dumps(previous), encoding="utf-8")
    with pytest.raises(QualificationError, match="complete image set"):
        rollback_gate(current_path, previous_path)


@pytest.mark.parametrize(
    ("current_version", "candidate_version", "message"),
    [
        ("v1.0.0-rc.8", "v1.0.0-rc.8", "prior distinct"),
        ("v1.0.0-rc.8", "v1.0.0-rc.9", "must predate"),
        ("v1.0.0-rc.8", "v1.0.0", "must predate"),
        ("v1.0.0", "v1.0.1-rc.1", "must predate"),
        ("v1.0", "v1.0.0-rc.7", "not governed"),
    ],
)
def test_rollback_gate_rejects_equal_newer_or_ungoverned_versions(
    tmp_path: Path,
    current_version: str,
    candidate_version: str,
    message: str,
) -> None:
    current_directory, current_records = _records(tmp_path / "current")
    previous_directory, previous_records = _records(tmp_path / "previous")
    current = release_manifest(
        current_records,
        version=current_version,
        commit=COMMIT,
        repository=SOURCE_REPOSITORY,
    )
    previous = release_manifest(
        previous_records,
        version=candidate_version,
        commit=COMMIT,
        repository=SOURCE_REPOSITORY,
    )
    configuration = {
        "sourceBundleSha256": {"production": "1" * 64},
        "resolvedBundleSha256": {"production": "2" * 64},
    }
    current["configuration"] = configuration
    previous["configuration"] = configuration
    current_path = current_directory / "release-images.json"
    previous_path = previous_directory / "release-images.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    previous_path.write_text(json.dumps(previous), encoding="utf-8")

    with pytest.raises(QualificationError, match=message):
        rollback_gate(current_path, previous_path)


@pytest.mark.parametrize(
    ("current_version", "candidate_version"),
    [
        ("v1.0.0-rc.8", "v1.0.0-rc.7"),
        ("v1.0.0", "v1.0.0-rc.8"),
        ("v1.1.0", "v1.0.9"),
        ("v2.0.0", "v1.99.99"),
    ],
)
def test_rollback_gate_accepts_only_earlier_governed_versions(
    tmp_path: Path,
    current_version: str,
    candidate_version: str,
) -> None:
    current_directory, current_records = _records(tmp_path / "current")
    previous_directory, previous_records = _records(tmp_path / "previous")
    current = release_manifest(
        current_records,
        version=current_version,
        commit=COMMIT,
        repository=SOURCE_REPOSITORY,
    )
    previous = release_manifest(
        previous_records,
        version=candidate_version,
        commit=COMMIT,
        repository=SOURCE_REPOSITORY,
    )
    configuration = {
        "sourceBundleSha256": {"production": "1" * 64},
        "resolvedBundleSha256": {"production": "2" * 64},
    }
    current["configuration"] = configuration
    previous["configuration"] = configuration
    current_path = current_directory / "release-images.json"
    previous_path = previous_directory / "release-images.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    previous_path.write_text(json.dumps(previous), encoding="utf-8")

    rollback_gate(current_path, previous_path)


@pytest.mark.parametrize(
    "image",
    [
        "registry.invalid/emg/identity@sha256:" + "1" * 64,
        "ghcr.io/emg/emg-platform/identity:latest",
        "ghcr.io/emg/emg-platform/identity@sha256:" + "0" * 64,
        "ghcr.io/emg/emg-platform/identity@sha256:" + "0" * 63 + "1",
    ],
)
def test_finalized_bundle_rejects_placeholders_mutable_tags_and_synthetic_digests(
    image: str,
) -> None:
    rendered = yaml.safe_dump(
        {"kind": "Pod", "spec": {"containers": [{"name": "identity", "image": image}]}}
    )
    with pytest.raises(ReleaseValidationError):
        validate_finalized_bundle(rendered, {"identity"})


def test_release_record_rejects_synthetic_digest(tmp_path: Path) -> None:
    sbom = tmp_path / "identity.cdx.json"
    sbom.write_text('{"bomFormat":"CycloneDX"}\n', encoding="utf-8")
    scan = tmp_path / "identity.trivy.sarif"
    scan.write_text('{"version":"2.1.0","runs":[{"results":[]}]}\n', encoding="utf-8")
    with pytest.raises(ReleaseValidationError, match="synthetic"):
        build_image_record(
            service="identity",
            owner="emg",
            digest="sha256:" + "a" * 64,
            commit=COMMIT,
            source_repository=SOURCE_REPOSITORY,
            workflow_identity="workflow",
            workflow_run="run",
            sbom_path=sbom,
            vulnerability_report_path=scan,
            provenance_reference="attestations",
        )
