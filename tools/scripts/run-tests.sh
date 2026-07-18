#!/usr/bin/env bash
# Runs the unit-test suite across all workspace packages using the repo .venv
# interpreter (never a globally-installed pytest). Extra args are passed through
# to pytest, e.g.:  ./tools/scripts/run-tests.sh libs/python/emg-connectors -q
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/scripts/_venv.sh
source "$SCRIPT_DIR/_venv.sh"
cd "$ROOT_DIR"

emg_require_venv
emg_print_env_banner

# Note: `-print -quit` (not `find ... | grep -q`) avoids a SIGPIPE/pipefail race
# that could make the guard spuriously report "no tests".
if [ -n "$(find libs services -name 'test_*.py' -print -quit 2>/dev/null)" ]; then
  exec "$VENV_PY" -m pytest "$@"
else
  echo "No tests exist yet — unit-tests stage is a no-op (Sprint 1 scaffold)"
fi
