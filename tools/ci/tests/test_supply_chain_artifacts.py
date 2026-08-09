import json
import re
import subprocess
import sys
from pathlib import Path

import yaml
from tools.ci.generate_sbom import generate

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
EXPECTED_LOCAL_COMPONENTS = {
    "emg-api-contracts",
    "emg-audit-client",
    "emg-audit-pipeline",
    "emg-auth-client",
    "emg-common-types",
    "emg-connectors",
    "emg-errors",
    "emg-knowledge-lifecycle",
    "emg-knowledge-pipeline",
    "emg-memory-graph",
    "emg-ontology",
    "emg-persistence",
    "emg-platform-core",
    "emg-policy-engine",
    "emg-semantic-layer",
    "emg-telemetry",
    "emg-trust-scoring",
    "emg-audit-projector",
    "emg-audit-service",
    "emg-identity",
    "emg-knowledge-graph-service",
    "emg-studio-bff",
}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_sbom_is_deterministic_and_sorted(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text("zeta==2.0 \\\n  --hash=x\nalpha==1.0 \\\n  --hash=y\n")
    first = generate(lock)
    second = generate(lock)
    assert first == second
    assert [item["name"] for item in first["components"]] == ["alpha", "zeta"]
    assert json.dumps(first, sort_keys=True)


def test_sbom_parses_repository_toml_and_covers_expected_components() -> None:
    payload = generate(
        ROOT / "requirements-production.lock",
        repository_root=ROOT,
        version="test-release",
    )
    components = payload["components"]
    names = {component["name"] for component in components}

    assert payload["bomFormat"] == "CycloneDX"
    assert payload["specVersion"] == "1.5"
    assert names >= EXPECTED_LOCAL_COMPONENTS
    assert len(components) == len({component["purl"] for component in components})


def test_repository_sbom_is_byte_deterministic(tmp_path: Path) -> None:
    command = [
        sys.executable,
        str(ROOT / "tools/ci/generate_sbom.py"),
        "--version",
        "deterministic-release",
    ]
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    subprocess.run([*command, "--output", str(first)], cwd=ROOT, check=True)
    subprocess.run([*command, "--output", str(second)], cwd=ROOT, check=True)

    assert first.read_bytes() == second.read_bytes()


def test_release_provenance_job_pins_stdlib_tomllib_python_and_artifact_paths() -> None:
    job = _workflow()["jobs"]["release-provenance"]
    steps = {step["name"]: step for step in job["steps"]}
    setup = steps["Set up Python 3.11"]
    build = steps["Build reproducible release artifacts"]["run"]

    assert re.fullmatch(r"actions/setup-python@[0-9a-f]{40}", setup["uses"])
    assert setup["with"]["python-version"] == "3.11"
    assert "python tools/ci/generate_sbom.py" in build
    assert "python tools/ci/generate_provenance.py" in build
    assert steps["Attest release artifacts"]["with"]["subject-path"] == "dist/*"
    assert steps["Upload release artifacts"]["with"]["path"] == "dist/"


def test_no_standalone_tomli_install_bypasses_hash_lock() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert not re.search(r"pip(?:3)? install[^\n]*\btomli\b", workflow_text)
    assert 'tomli>=2.0; python_version < "3.11"' in (ROOT / "requirements-dev.txt").read_text(
        encoding="utf-8"
    )
