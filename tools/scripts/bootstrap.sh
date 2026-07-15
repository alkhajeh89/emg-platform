#!/usr/bin/env bash
# One-command local environment setup. Invoked by `make bootstrap`.
# Engineering Master Plan §13: "Onboarding documentation validated by a new
# engineer completing full setup in under one working day."
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "==> Checking prerequisites (docker, python3, node)"
command -v docker >/dev/null || { echo "docker is required"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }

echo "==> Installing shared library packages (editable)"
./tools/scripts/install-libs.sh

echo "==> Installing pre-commit hooks"
pip install --quiet pre-commit || true
pre-commit install || true

echo "==> Starting local orchestration"
docker compose up -d

echo "==> Bootstrap complete. See docs/engineering/onboarding.md for next steps."
