from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import check_dependency_drift as drift  # noqa: E402
import check_dependency_manifest as manifest_check  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def _service(root: Path, relative_path: str) -> None:
    service = root / relative_path
    service.mkdir(parents=True)
    (service / "service.yaml").write_text("name: example\n")
    (service / "Dockerfile").write_text("FROM scratch\n")


def test_audit_projector_is_registered_with_accurate_dependencies() -> None:
    manifest = manifest_check.load_manifest(ROOT)
    projector = manifest["services"]["audit-projector"]

    assert projector == {
        "type": "service",
        "path": "services/audit-projector",
        "dockerfile": "services/audit-projector/Dockerfile",
        "dependencies": [
            "emg-audit-client",
            "emg-common-types",
            "emg-persistence",
            "emg-telemetry",
        ],
    }
    actual = drift.get_pyproject_dependencies(ROOT / "services/audit-projector/pyproject.toml")
    assert actual == set(projector["dependencies"])
    assert manifest_check.check_component("audit-projector", projector, ROOT)


def test_keycloak_provisioner_is_registered_as_emg_built_deployment_tool() -> None:
    manifest = manifest_check.load_manifest(ROOT)
    provisioner = manifest["services"]["keycloak-provisioner"]

    assert provisioner == {
        "type": "deployment-tool",
        "path": "tools",
        "dockerfile": "tools/keycloak-provisioner.Dockerfile",
        "dependencies": ["emg-common-types"],
    }
    assert manifest_check.check_component("keycloak-provisioner", provisioner, ROOT)
    dockerfile = (ROOT / provisioner["dockerfile"]).read_text(encoding="utf-8")
    assert "tools/scripts/provision-keycloak-realm.py" in dockerfile


def test_real_repository_has_complete_production_service_coverage() -> None:
    manifest = manifest_check.load_manifest(ROOT)

    assert manifest_check.check_production_service_coverage(manifest, ROOT)


def test_audit_projector_registration_removal_or_corruption_fails() -> None:
    manifest = manifest_check.load_manifest(ROOT)
    missing = deepcopy(manifest)
    missing["services"].pop("audit-projector")
    corrupt = deepcopy(manifest)
    corrupt["services"]["audit-projector"]["dockerfile"] = "services/audit/Dockerfile"

    assert not manifest_check.check_production_service_coverage(missing, ROOT)
    assert not manifest_check.check_production_service_coverage(corrupt, ROOT)


def test_missing_production_service_registration_fails(tmp_path: Path) -> None:
    _service(tmp_path, "services/unregistered")
    manifest = {"services": {}}

    assert not manifest_check.check_production_service_coverage(manifest, tmp_path)


def test_corrupt_production_service_registration_fails(tmp_path: Path) -> None:
    _service(tmp_path, "apps/example")
    manifest = {
        "services": {
            "example": {
                "type": "service",
                "path": "apps/example",
                "dockerfile": "services/example/Dockerfile",
            }
        }
    }

    assert not manifest_check.check_production_service_coverage(manifest, tmp_path)
