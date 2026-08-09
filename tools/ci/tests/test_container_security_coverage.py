from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def _governed_images() -> set[str]:
    manifest = yaml.safe_load((ROOT / "docker/dependencies.yaml").read_text())
    return {
        name
        for name, component in manifest["services"].items()
        if component.get("type") in {"service", "deployment-tool"}
    }


def test_container_security_matrix_covers_every_production_service() -> None:
    inventory = _workflow()["jobs"]["container-inventory"]
    job = _workflow()["jobs"]["container-security"]

    assert "runtime_image_release.py inventory --github-output" in inventory["steps"][-1]["run"]
    assert job["needs"] == "container-inventory"
    assert "fromJSON(needs.container-inventory.outputs.matrix)" in job["strategy"]["matrix"]
    assert _governed_images() == {
        "identity",
        "audit",
        "audit-projector",
        "knowledge-graph",
        "studio-bff",
        "keycloak-provisioner",
    }


def test_container_security_matrix_uses_one_mandatory_trivy_policy() -> None:
    job = _workflow()["jobs"]["container-security"]
    scan = next(
        step
        for step in job["steps"]
        if step["name"] == "Scan image (critical vulnerabilities block)"
    )

    assert "matrix.service" in scan["with"]["image-ref"]
    assert scan["with"]["severity"] == "CRITICAL"
    assert scan["with"]["ignore-unfixed"] is True
    assert scan["with"]["exit-code"] == "1"
    assert "continue-on-error" not in scan
