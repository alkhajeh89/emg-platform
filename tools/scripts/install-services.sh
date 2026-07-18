#!/usr/bin/env bash
# Installs every installable services/* package in EDITABLE mode with its [dev]
# extra. This is what makes root test discovery work: the root pyproject.toml
# points pytest at both `libs` and `services`, and the service test suites
# import their own package (e.g. `emg_identity`, `emg_audit_service`) plus
# third-party runtime deps (fastapi, httpx, pyjwt[crypto] -> cryptography,
# psycopg, pydantic-settings) and test deps (pytest-asyncio).
#
# Only directories that ship a pyproject.toml are installable services; empty
# scaffold directories under services/ are skipped automatically.
#
# Run AFTER install-libs.sh so each service's emg-* siblings are already present
# (resolved locally); the remaining third-party deps come from the index.
#
# Idempotent: re-running re-installs the editable projects in place.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/scripts/_venv.sh
source "$SCRIPT_DIR/_venv.sh"
SERVICES_DIR="$ROOT_DIR/services"

if [ ! -d "$SERVICES_DIR" ]; then
  echo "==> No services directory found — nothing to install"
  exit 0
fi

shopt -s nullglob
pkgs=("$SERVICES_DIR"/*/pyproject.toml)
if [ ${#pkgs[@]} -eq 0 ]; then
  echo "==> No installable service packages (no services/*/pyproject.toml) — nothing to install"
  exit 0
fi

if [ -x "$VENV_PY" ]; then
  PIP=("$VENV_PY" -m pip)
else
  echo "WARNING: .venv not found; using ambient '$(command -v python3)'. Run 'make bootstrap' for the isolated env." >&2
  PIP=(python3 -m pip)
fi

args=()
names=()
for pkg in "${pkgs[@]}"; do
  dir="$(dirname "$pkg")"
  args+=(-e "${dir}[dev]")
  names+=("$(basename "$dir")")
done

echo "==> Installing ${#names[@]} service package(s) (editable, [dev]):"
printf '      - %s\n' "${names[@]}"
"${PIP[@]}" install "${args[@]}"
echo "==> Service packages installed (emg_identity / emg_audit_service + fastapi, cryptography, httpx, pytest-asyncio, ...)."
