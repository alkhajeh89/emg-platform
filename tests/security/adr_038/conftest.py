"""Session-scoped fixtures for the ADR-038 non-production capability
verification suite.

Running `pytest tests/security/adr_038` from repo root is fully
self-contained: it brings up the isolated verification Keycloak (its own
compose project/network/ports, never the shared `emg-keycloak` on :8080),
runs provision.py's post-import steps, and tears the whole thing down again
at the end unless EMG_VERIFICATION_KEEP_UP=1 is set in the environment
(useful for interactive debugging).

This directory, its docker-compose file, and its realm import are isolated
from -- and never modify -- ./docker-compose.yml or either committed
Keycloak realm artifact at the repo root.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).parent

# The repo's pytest config uses --import-mode=importlib (see pyproject.toml),
# which does not add a test file's own directory to sys.path. This suite's
# sibling helper modules (keycloak_client, claim_adapter,
# downstream_validator) are plain local imports, not an installed package --
# add this directory explicitly so `import keycloak_client` etc. resolve.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

ENV_FILE = HERE / ".env.verification.local"
COMPOSE_FILE = HERE / "docker-compose.verification.yml"
BASE_URL = "http://localhost:8180"
REALM = "emg-verification"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=HERE, check=True, **kwargs)


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            values[k] = v
    return values


@pytest.fixture(scope="session")
def verification_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        _run(["./generate_env.sh"])

    env = os.environ.copy()
    env.update(_load_env())

    _run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(COMPOSE_FILE),
            "up",
            "-d",
        ],
        env=env,
    )

    deadline = time.time() + 90
    healthy = False

    while time.time() < deadline:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                "emg-adr038-verification-keycloak",
            ],
            capture_output=True,
            text=True,
        )

        if result.stdout.strip() == "healthy":
            healthy = True
            break

        time.sleep(2)

    if not healthy:
        logs = subprocess.run(
            [
                "docker",
                "logs",
                "emg-adr038-verification-keycloak",
            ],
            capture_output=True,
            text=True,
        )

        message = (
            "verification Keycloak never became healthy.\n"
            f"{logs.stdout[-4000:]}\n"
            f"{logs.stderr[-2000:]}"
        )

        pytest.fail(message)

    _run([sys.executable, "provision.py"], env=env)

    values = _load_env()
    values["base_url"] = BASE_URL
    values["realm"] = REALM

    yield values

    if os.environ.get("EMG_VERIFICATION_KEEP_UP") != "1":
        subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ENV_FILE),
                "-f",
                str(COMPOSE_FILE),
                "down",
                "-v",
            ],
            cwd=HERE,
            env=env,
        )
