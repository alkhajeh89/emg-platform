#!/usr/bin/env bash
# Auto-format + lint-fix across all workspace packages, using the repo .venv
# tools (never globally-installed ruff/black). Configuration comes from the root
# pyproject.toml ([tool.ruff], [tool.black]).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/scripts/_venv.sh
source "$SCRIPT_DIR/_venv.sh"
cd "$ROOT_DIR"

emg_require_venv

# `-print -quit` (not `find ... | grep -q`) avoids a SIGPIPE/pipefail race.
if [ -n "$(find libs services -name '*.py' -print -quit 2>/dev/null)" ]; then
  "$VENV_PY" -m ruff check --fix libs services
  "$VENV_PY" -m black libs services
else
  echo "No Python sources yet — format is a no-op"
fi
