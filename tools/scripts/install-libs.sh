#!/usr/bin/env bash
# Installs every libs/python/* package in EDITABLE mode with its [dev] extra.
#
# The EMG shared libraries depend on each other by name (e.g. emg-connectors ->
# emg-common-types, emg-errors) and are PROPRIETARY — they are not published to
# PyPI or any index. Installing them one-at-a-time fails because a package's
# sibling dependency is not yet present and pip then tries (and fails) to fetch
# it from the index.
#
# Fix: pass EVERY local package to a SINGLE `pip install -e ...` invocation. pip
# treats all projects on the command line as candidates and resolves the emg-*
# sibling requirements against them locally, so nothing proprietary is fetched
# from the index and installation order is irrelevant (no topological sort
# needed). Third-party deps (pydantic, pyyaml, ...) still resolve from the index.
#
# Idempotent: re-running simply re-installs the editable projects in place.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/scripts/_venv.sh
source "$SCRIPT_DIR/_venv.sh"
LIBS_DIR="$ROOT_DIR/libs/python"

if [ ! -d "$LIBS_DIR" ]; then
  echo "==> No libs/python directory found — nothing to install"
  exit 0
fi

shopt -s nullglob
pkgs=("$LIBS_DIR"/*/pyproject.toml)
if [ ${#pkgs[@]} -eq 0 ]; then
  echo "==> No Python packages under libs/python — nothing to install"
  exit 0
fi

# Prefer the repo .venv; fall back to the ambient interpreter (with a warning)
# so the script still works if run standalone before bootstrap finishes.
if [ -x "$VENV_PY" ]; then
  PIP=("$VENV_PY" -m pip)
else
  echo "WARNING: .venv not found; using ambient '$(command -v python3)'. Run 'make bootstrap' for the isolated env." >&2
  PIP=(python3 -m pip)
fi

args=()
names=()
skipped=()
for pkg in "${pkgs[@]}"; do
  dir="$(dirname "$pkg")"
  # Skip an unpopulated library scaffold: a 0-byte (or whitespace-only)
  # pyproject.toml has no [build-system]/[project] table, so it is not yet a
  # real, ownership-decided package -- mirrors how a services/* directory
  # with NO pyproject.toml at all is already skipped by install-services.sh.
  # See docs/architecture/EMG_ARCHITECTURE_DECISION_REGISTER.md D-A-002 for
  # the specific case (libs/python/emg-entity-resolution) this generalizes
  # from; this check is name-agnostic so it applies to any future premature
  # scaffold, not just that one.
  if [ -z "$(tr -d '[:space:]' < "$pkg")" ]; then
    skipped+=("$(basename "$dir")")
    continue
  fi
  args+=(-e "${dir}[dev]")
  names+=("$(basename "$dir")")
done

if [ ${#skipped[@]} -gt 0 ]; then
  echo "==> Skipping ${#skipped[@]} unpopulated library scaffold(s) (empty pyproject.toml, not yet installable):"
  printf '      - %s\n' "${skipped[@]}"
fi

echo "==> Installing ${#names[@]} local library packages (editable, [dev]) in one resolver pass:"
printf '      - %s\n' "${names[@]}"
"${PIP[@]}" install "${args[@]}"
echo "==> Library packages installed."
