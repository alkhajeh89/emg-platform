#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
PYTHON_BIN="${EMG_BACKUP_PYTHON:-python3}"

# ADR-043 Amendment 1 A9.3: identifies every PostgreSQL session authenticated
# as emg_identity_app against the recovery target, terminates it, re-queries
# to prove none survive, and writes non-secret positive evidence only after
# the re-query succeeds (emg_persistence.provisioning.
# terminate_and_prove_identity_app_sessions_excluded). Authenticates with the
# governed database-bootstrap-administrator credential (D-8) -- never
# emg_identity_app, and never emg_identity_migrator either, because
# pg_terminate_backend requires a privilege neither of those two
# NOSUPERUSER/no-membership constrained roles (D-2) may hold. No new
# credential is introduced: this reuses the existing
# EMG_DATABASE_BOOTSTRAP_ADMIN_DSN reference already delivered through the
# emg-database-bootstrap-secrets ExternalSecret.
: "${EMG_DATABASE_BOOTSTRAP_ADMIN_DSN:?must be supplied by the secret store}"
: "${EMG_IDENTITY_RECOVERY_TARGET_ENVIRONMENT:?must identify the environment being recovered, e.g. production}"
: "${EMG_IDENTITY_RECOVERY_FENCE_ACTOR:?must identify the fence owner (A9.1) for the audit trail}"
: "${EMG_IDENTITY_SESSION_FENCE_EVIDENCE:?must be an absolute path to write the session-fence evidence file}"
[[ "$EMG_IDENTITY_SESSION_FENCE_EVIDENCE" = /* ]] || die "EMG_IDENTITY_SESSION_FENCE_EVIDENCE must be absolute"

"$PYTHON_BIN" -m emg_persistence.provisioning identity-session-fence

printf 'database-session fence established: %s\n' "$EMG_IDENTITY_SESSION_FENCE_EVIDENCE"
