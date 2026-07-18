#!/usr/bin/env bash
# Shared helpers for the EMG bootstrap/dev scripts. This file is SOURCED, not
# executed — it defines the repository paths, the .venv interpreter locations,
# and a couple of guard functions used by run-tests.sh / run-lint.sh / etc.
#
# Every consumer gets:
#   ROOT_DIR   - absolute repo root
#   VENV_DIR   - .venv location (overridable with EMG_VENV)
#   VENV_PY    - .venv/bin/python
#   VENV_PIP   - .venv/bin/pip
#   emg_supported_python <interpreter>  - returns 0 iff 3.10 <= ver < 3.13
#   emg_require_venv                     - clear error + exit if .venv missing

# Resolve repo root from THIS file's location (works regardless of caller cwd).
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${EMG_VENV:-$ROOT_DIR/.venv}"
VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Supported interpreter range for the whole monorepo. The tooling targets 3.10
# (root pyproject.toml: ruff/black target py310, mypy python_version 3.10) and
# is validated on 3.10-3.12. 3.13+/3.14 are deliberately NOT accepted here so a
# machine whose default `python3` is newer (e.g. Homebrew python@3.14) does not
# silently produce an unsupported environment.
emg_supported_python() {
  "$1" -c 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,13) else 1)' 2>/dev/null
}

emg_require_venv() {
  if [ ! -x "$VENV_PY" ]; then
    echo "ERROR: no virtual environment found at ${VENV_DIR}." >&2
    echo "       Run 'make bootstrap' first, then 'source .venv/bin/activate'." >&2
    exit 1
  fi
}

# Prints exactly which interpreter/cwd/path this script is about to run Python
# with, BEFORE it does so. Exists so "everything imports here, nothing imports
# there" discrepancies are never a mystery: every consumer (bootstrap.sh,
# setup-check.sh, run-tests.sh) prints this immediately before invoking
# $VENV_PY, so the terminal output itself always shows which interpreter,
# which cwd, and which sys.path were actually used for that run.
emg_print_env_banner() {
  echo "--- environment ---"
  echo "pwd:            $(pwd)"
  echo "ROOT_DIR:       $ROOT_DIR"
  echo "which python:   $(command -v python || echo 'not on PATH')"
  echo "which pytest:   $(command -v pytest || echo 'not on PATH')"
  echo "VENV_PY:        $VENV_PY $([ -x "$VENV_PY" ] && echo '(exists)' || echo '(MISSING)')"
  if [ -x "$VENV_PY" ]; then
    "$VENV_PY" -c "
import sys, os
print('sys.executable:', sys.executable)
print('os.getcwd():   ', os.getcwd())
print('sys.path[:5]:  ', sys.path[:5])
"
  fi
  echo "-------------------"
}
