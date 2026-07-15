#!/usr/bin/env bash
# Installs every /libs Python package in editable mode.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIBS_DIR="$ROOT_DIR/libs/python"

if [ ! -d "$LIBS_DIR" ]; then
  echo "No libs/python directory found — nothing to install"
  exit 0
fi

shopt -s nullglob
pkgs=("$LIBS_DIR"/*/pyproject.toml)
if [ ${#pkgs[@]} -eq 0 ]; then
  echo "No Python packages under libs/python — nothing to install"
  exit 0
fi

for pkg in "${pkgs[@]}"; do
  dir="$(dirname "$pkg")"
  echo "==> Installing $(basename "$dir") (editable, dev extras)"
  pip install --quiet -e "$dir[dev]" || pip install --quiet -e "$dir"
done
