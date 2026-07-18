#!/usr/bin/env bash
# Static type-check gate (TD-001). Runs `mypy` (strict, from the root
# pyproject [tool.mypy]) on each package's src/ SEPARATELY.
#
# Why per-package and not `mypy libs services` in one shot: many packages ship a
# tests/ package with its own tests/__init__.py, and a single aggregate mypy
# invocation maps them all to the same module name "tests" and aborts with
# "Duplicate module named 'tests'" before type-checking anything. Iterating
# per-package avoids the collision entirely. See
# docs/engineering/technical-debt.md (TD-001).
#
# This is intentionally a SEPARATE gate from `make lint` (ruff + black); it does
# not change lint behaviour. Uses the repo .venv only.
#
# Intentionally NOT `set -e`: run every package and report all failures, rather
# than stop at the first.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/scripts/_venv.sh
source "$SCRIPT_DIR/_venv.sh"
cd "$ROOT_DIR"

emg_require_venv
emg_print_env_banner

fail=0
checked=0
failed_pkgs=()

for pkg in libs/python/*/ services/*/; do
  src="${pkg}src"
  [ -d "$src" ] || continue
  # Skip empty scaffolds (no Python sources yet).
  if [ -z "$(find "$src" -name '*.py' -print -quit 2>/dev/null)" ]; then
    continue
  fi
  echo "== mypy: ${pkg%/} =="
  if ! "$VENV_PY" -m mypy "$src"; then
    fail=1
    failed_pkgs+=("${pkg%/}")
  fi
  checked=$((checked + 1))
done

echo "-------------------"
if [ "$checked" -eq 0 ]; then
  echo "No package sources to type-check (nothing to do)."
  exit 0
fi
if [ "$fail" -ne 0 ]; then
  echo "Type-check FAILED in: ${failed_pkgs[*]}" >&2
  exit 1
fi
echo "Type-check passed (mypy --strict) for ${checked} package(s)."
