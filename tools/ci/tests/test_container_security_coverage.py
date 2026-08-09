from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def _production_services() -> set[str]:
    manifest = yaml.safe_load((ROOT / "docker/dependencies.yaml").read_text())
    return {
        name
        for name, component in manifest["services"].items()
        if component.get("type") == "service"
    }


def test_container_security_matrix_covers_every_production_service() -> None:
    job = _workflow()["jobs"]["container-security"]

    assert set(job["strategy"]["matrix"]["service"]) == _production_services()
    assert "audit-projector" in job["strategy"]["matrix"]["service"]


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
