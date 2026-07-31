#!/usr/bin/env bash
# One-command local environment setup. Invoked by `make bootstrap`.
# Engineering Master Plan §13: "Onboarding documentation validated by a new
# engineer completing full setup in under one working day."
#
# What it does (all steps are idempotent — safe to re-run):
#   1. Check prerequisites (python3 required; docker/node optional/soft).
#   2. Select a SUPPORTED Python interpreter (3.10-3.12) — never silently a
#      newer default like 3.14.
#   3. Create/repair an isolated .venv (does NOT rely on shell activation).
#   4. Install the developer toolchain (requirements-dev.txt).
#   5. Editable-install all local libs + service packages (siblings resolve
#      locally — nothing proprietary is fetched from PyPI).
#   6. Install pre-commit git hooks.
#   7. Seed .env from .env.example.
#   8. Start local infra with docker compose (soft — skipped if unavailable).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tools/scripts/_venv.sh
source "$SCRIPT_DIR/_venv.sh"
cd "$ROOT_DIR"
emg_print_env_banner

SUPPORTED="3.10, 3.11, or 3.12"
PIN_FILE="$ROOT_DIR/.python-version"

log() { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
log "Checking prerequisites"
command -v python3 >/dev/null 2>&1 || die "python3 is required but was not found on PATH."
command -v docker  >/dev/null 2>&1 || warn "docker not found — local infra ('make up') will be unavailable until Docker is installed."
command -v node    >/dev/null 2>&1 || warn "node not found — front-end tooling (apps/) will be unavailable until Node 20+ is installed."

# ---------------------------------------------------------------------------
# 2. Select a supported Python interpreter
# ---------------------------------------------------------------------------
PYBIN=""
if [ -n "${EMG_PYTHON:-}" ]; then
  emg_supported_python "$EMG_PYTHON" \
    || die "EMG_PYTHON=$EMG_PYTHON is outside the supported range ($SUPPORTED)."
  PYBIN="$EMG_PYTHON"
else
  pinned="$(head -n1 "$PIN_FILE" 2>/dev/null | tr -d '[:space:]')"
  candidates=()
  [ -n "$pinned" ] && candidates+=("python${pinned}")
  candidates+=(python3.10 python3.11 python3.12 python3)
  for c in "${candidates[@]}"; do
    if command -v "$c" >/dev/null 2>&1 && emg_supported_python "$c"; then
      PYBIN="$(command -v "$c")"
      break
    fi
  done
fi

if [ -z "$PYBIN" ]; then
  default_ver="$(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null || echo "unknown")"
  echo "ERROR: no supported Python interpreter found." >&2
  echo "       EMG targets Python $SUPPORTED (pinned to '$(cat "$PIN_FILE" 2>/dev/null || echo 3.10)' in .python-version)." >&2
  echo "       Your default 'python3' is $default_ver, which is not supported." >&2
  echo "       Fix it by installing a supported interpreter, e.g. with pyenv:" >&2
  echo "           pyenv install 3.10 && pyenv local 3.10" >&2
  echo "       or point bootstrap at one explicitly:" >&2
  echo "           EMG_PYTHON=/path/to/python3.10 make bootstrap" >&2
  exit 1
fi
log "Using interpreter: $PYBIN ($("$PYBIN" -V 2>&1))"

# ---------------------------------------------------------------------------
# 3. Create / repair the virtual environment (idempotent)
# ---------------------------------------------------------------------------
recreate=0
if [ -d "$VENV_DIR" ]; then
  if [ -x "$VENV_PY" ] && emg_supported_python "$VENV_PY"; then
    log ".venv already present and supported ($("$VENV_PY" -V 2>&1)) — reusing"
  else
    warn ".venv exists but its interpreter is missing/broken or unsupported — recreating it"
    recreate=1
  fi
else
  recreate=1
fi
if [ "$recreate" -eq 1 ]; then
  rm -rf "$VENV_DIR"
  log "Creating virtual environment at .venv"
  "$PYBIN" -m venv "$VENV_DIR"
fi

# ---------------------------------------------------------------------------
# 4. Base tooling + dev toolchain
# ---------------------------------------------------------------------------
emg_print_env_banner
log "Installing the hash-locked developer toolchain (requirements-dev.lock)"
"$VENV_PY" -m pip install --quiet --require-hashes \
  -r "$ROOT_DIR/requirements-dev.lock"

# ---------------------------------------------------------------------------
# 5. Editable install of every local package (libs first, then services)
# ---------------------------------------------------------------------------
"$SCRIPT_DIR/install-libs.sh"
"$SCRIPT_DIR/install-services.sh"

# ---------------------------------------------------------------------------
# 5b. Verify every editable install actually resolves on THIS machine.
# ---------------------------------------------------------------------------
# `pip install -e` can report success while still leaving an unimportable
# package: hatchling's .pth file bakes in an absolute path, and CPython's
# site.py silently drops any .pth line whose path fails os.path.exists() (no
# error, no warning). That is a real, distinct failure mode from "install
# failed" — see tools/scripts/diagnose_editable_installs.py and
# docs/engineering/editable-install-troubleshooting.md. Since bootstrap just
# ran a fresh install-libs.sh/install-services.sh against the CURRENT repo
# path above, any drift from a previous install is already corrected; this
# step exists purely to make that fact loud and verified rather than assumed.
log "Verifying editable installs resolve on this machine"
if ! "$VENV_PY" "$SCRIPT_DIR/diagnose_editable_installs.py"; then
  warn "one or more editable installs still do not resolve — see the detail above."
  warn "This is not fixed by recreating .venv; it means a package's pyproject.toml"
  warn "packages=[...] entry does not match its real src/ layout. Investigate before continuing."
fi

# ---------------------------------------------------------------------------
# 6. Pre-commit hooks
# ---------------------------------------------------------------------------
if [ -x "$VENV_DIR/bin/pre-commit" ]; then
  log "Installing pre-commit git hooks"
  "$VENV_DIR/bin/pre-commit" install
else
  warn "pre-commit not installed in .venv — skipping git hook installation."
fi

# ---------------------------------------------------------------------------
# 7. .env
# ---------------------------------------------------------------------------
if [ -f "$ROOT_DIR/.env" ]; then
  log ".env already present — leaving it untouched"
else
  log "Creating .env from .env.example (local-development defaults)"
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
fi

# ---------------------------------------------------------------------------
# 8. Local orchestration (soft — never blocks make test/lint)
# ---------------------------------------------------------------------------
if [ "${EMG_SKIP_DOCKER:-0}" = "1" ]; then
  log "EMG_SKIP_DOCKER=1 — skipping 'docker compose up'"
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  log "Starting local orchestration (docker compose up -d)"
  docker compose -f "$ROOT_DIR/docker-compose.yml" up -d \
    || warn "'docker compose up' failed — infra not started. You can still run 'make test' and 'make lint'."
else
  warn "Docker not available/running — skipping local infra. Start it later with 'make up'."
fi

echo
log "Bootstrap complete."
log "Activate the environment:   source .venv/bin/activate"
log "Then verify:                make test  &&  make lint"
log "Details & troubleshooting:  docs/engineering/onboarding.md"
