import json
from pathlib import Path

from tools.ci.generate_sbom import generate


def test_sbom_is_deterministic_and_sorted(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text("zeta==2.0 \\\n  --hash=x\nalpha==1.0 \\\n  --hash=y\n")
    first = generate(lock)
    second = generate(lock)
    assert first == second
    assert [item["name"] for item in first["components"]] == ["alpha", "zeta"]
    assert json.dumps(first, sort_keys=True)
