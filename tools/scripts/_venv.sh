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
