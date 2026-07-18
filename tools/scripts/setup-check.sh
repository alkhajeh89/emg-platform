#!/usr/bin/env bash
# Non-destructive diagnostic for the local developer environment. Reports what
# is and isn't ready without changing anything. Invoked by `make setup-check`.
# Exits non-zero if any REQUIRED check fails, so it is CI/script friendly.
#
# Intentionally does NOT use `set -e`: we want to run every check and print a
# full report rather than stop at the first failure.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/scripts/_venv.sh
source "$SCRIPT_DIR/_venv.sh"
cd "$ROOT_DIR"

fail=0
pass_line() { printf '  [ OK ] %s\n' "$*"; }
fail_line() { printf '  [FAIL] %s\n' "$*"; fail=1; }
warn_line() { printf '  [WARN] %s\n' "$*"; }

echo "EMG local environment check"
echo "==========================="

# --- Interpreter / venv -----------------------------------------------------
echo "Virtual environment:"
if [ -x "$VENV_PY" ]; then
  ver="$("$VENV_PY" -V 2>&1)"
  if emg_supported_python "$VENV_PY"; then
    pass_line ".venv present ($ver, supported)"
  else
    fail_line ".venv present but interpreter $ver is OUTSIDE the supported range (3.10-3.12). Re-run 'make bootstrap'."
  fi
else
  fail_line "no .venv — run 'make bootstrap'"
fi

# --- Developer toolchain ----------------------------------------------------
echo "Developer toolchain (.venv):"
if [ -x "$VENV_PY" ]; then
  for tool in pytest ruff black mypy pre_commit build pip_audit; do
    modname="$tool"
    case "$tool" in
      pre_commit) importname="pre_commit" ;;
      pip_audit)  importname="pip_audit" ;;
      *)          importname="$tool" ;;
    esac
    if "$VENV_PY" -c "import ${importname}" 2>/dev/null; then
      pass_line "$importname importable"
    else
      fail_line "$importname missing — re-run 'make bootstrap'"
    fi
  done
else
  warn_line "skipped (no .venv)"
fi

# --- Local package imports --------------------------------------------------
echo "Local package imports (.venv):"
if [ -x "$VENV_PY" ]; then
  for mod in emg_common_types emg_errors emg_connectors emg_identity emg_audit_service cryptography; do
    if "$VENV_PY" -c "import ${mod}" 2>/dev/null; then
      pass_line "$mod importable"
    else
      fail_line "$mod NOT importable — re-run 'make bootstrap'"
    fi
  done
else
  warn_line "skipped (no .venv)"
fi

# --- Supporting files -------------------------------------------------------
echo "Repository setup files:"
[ -f "$ROOT_DIR/.env" ] && pass_line ".env present" || warn_line ".env missing (copy from .env.example or re-run bootstrap)"
[ -f "$ROOT_DIR/.python-version" ] && pass_line ".python-version present" || fail_line ".python-version missing"
[ -f "$ROOT_DIR/.pre-commit-config.yaml" ] && pass_line ".pre-commit-config.yaml present" || fail_line ".pre-commit-config.yaml missing"

# --- Optional external tools ------------------------------------------------
echo "Optional tooling:"
command -v docker >/dev/null 2>&1 && pass_line "docker on PATH" || warn_line "docker not found (needed only for 'make up' local infra)"
command -v node   >/dev/null 2>&1 && pass_line "node on PATH"   || warn_line "node not found (needed only for apps/ front-end tooling)"

echo "==========================="
if [ "$fail" -eq 0 ]; then
  echo "Environment looks good. Run: source .venv/bin/activate && make test && make lint"
else
  echo "One or more REQUIRED checks failed. Run 'make bootstrap' and re-check."
fi
exit "$fail"
