#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIBS_DIR="$ROOT_DIR/libs/python"

shopt -s nullglob
pkgs=("$LIBS_DIR"/*/pyproject.toml)
if [ ${#pkgs[@]} -eq 0 ]; then
  echo "No Python packages to audit yet — no-op"
  exit 0
fi

for pkg in "${pkgs[@]}"; do
  dir="$(dirname "$pkg")"
  echo "==> Auditing $(basename "$dir")"
  pip-audit --path "$dir" || true
done
