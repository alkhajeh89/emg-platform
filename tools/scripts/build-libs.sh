#!/usr/bin/env bash
# Builds every /libs Python package (sdist + wheel) via the `build` module.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIBS_DIR="$ROOT_DIR/libs/python"

if [ ! -d "$LIBS_DIR" ]; then
  echo "No libs/python directory found — nothing to build"
  exit 0
fi

shopt -s nullglob
pkgs=("$LIBS_DIR"/*/pyproject.toml)
if [ ${#pkgs[@]} -eq 0 ]; then
  echo "No Python packages under libs/python — nothing to build"
  exit 0
fi

pip install --quiet build
for pkg in "${pkgs[@]}"; do
  dir="$(dirname "$pkg")"
  echo "==> Building $(basename "$dir")"
  python3 -m build --quiet "$dir"
done
