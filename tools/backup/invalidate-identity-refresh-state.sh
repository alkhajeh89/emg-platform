#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
require_command psql
PYTHON_BIN="${EMG_BACKUP_PYTHON:-python3}"
: "${EMG_IDENTITY_RECOVERY_DSN:?must be supplied by the secret store}"
: "${EMG_IDENTITY_RECOVERY_GENERATION:?must be supplied by the governed recovery orchestrator (A3.2)}"
: "${EMG_IDENTITY_RECOVERY_AUTHORITY_REVISION:?must be supplied by the governed recovery orchestrator (A3.2)}"

# ADR-043 Amendment 1 A6: one PostgreSQL transaction invalidates every
# restored refresh family/token, proves none remains valid, and records the
# externally-authoritative (generation, authority_revision) pair -- never a
# bare invalidation with no reconciled marker. Fence release remains
# governed separately by A9.6 regardless of this command's outcome.
EMG_IDENTITY_MIGRATION_POSTGRES_DSN="$EMG_IDENTITY_RECOVERY_DSN" \
EMG_IDENTITY_RECOVERY_GENERATION="$EMG_IDENTITY_RECOVERY_GENERATION" \
EMG_IDENTITY_RECOVERY_AUTHORITY_REVISION="$EMG_IDENTITY_RECOVERY_AUTHORITY_REVISION" \
"$PYTHON_BIN" -m emg_persistence.provisioning identity-reconcile

printf '%s\n' "restored Identity refresh state invalidated and reconciled"
