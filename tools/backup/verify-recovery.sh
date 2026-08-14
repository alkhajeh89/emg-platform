#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
PYTHON_BIN="${EMG_BACKUP_PYTHON:-python3}"
require_command pg_isready
require_command psql
: "${EMG_RESTORE_DSN:?must be supplied by the secret store}"
: "${EMG_IDENTITY_RECOVERY_DSN:?must be supplied by the secret store}"
[[ $# -eq 1 ]] || die "usage: verify-recovery.sh MANIFEST"
manifest="$1"
expected_major="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["postgres"]["majorVersion"])' "$manifest")"
expected_database="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["postgres"]["database"])' "$manifest")"
pg_isready --dbname="$EMG_RESTORE_DSN" --timeout=10
actual="$(psql "$EMG_RESTORE_DSN" -X --set=ON_ERROR_STOP=1 --tuples-only --no-align --field-separator='|' <<SQL
SELECT current_setting('server_version_num')::integer / 10000,
       current_database(),
       to_regclass('public.audit_events') IS NOT NULL,
       to_regclass('public.evidence_custody_events') IS NOT NULL,
       to_regclass('emg_identity.identity_refresh_token_families') IS NOT NULL,
       to_regclass('emg_identity.identity_refresh_tokens') IS NOT NULL,
       to_regclass('emg_identity.identity_schema_migrations') IS NOT NULL,
       EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='public'),
       NOT pg_is_in_recovery();
SQL
)"
IFS='|' read -r major database audit_table custody_table identity_families identity_tokens identity_history public_schema recovery_complete <<<"$actual"
[[ "$major" == "$expected_major" ]] || die "PostgreSQL major version mismatch"
[[ "$database" == "$expected_database" ]] || die "database identity mismatch"
[[ "$audit_table" == t && "$custody_table" == t && "$identity_families" == t && "$identity_tokens" == t && "$identity_history" == t && "$public_schema" == t ]] || die "required schema/tables missing"
[[ "$recovery_complete" == t ]] || die "PostgreSQL is still in recovery"
if [[ -n "${EMG_REQUIRED_EXTENSIONS:-}" ]]; then
  IFS=',' read -ra extensions <<<"$EMG_REQUIRED_EXTENSIONS"
  for extension in "${extensions[@]}"; do
    [[ "$extension" =~ ^[a-zA-Z0-9_-]+$ ]] || die "unsafe extension name"
    [[ "$(psql "$EMG_RESTORE_DSN" -XAtqc "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='$extension')")" == t ]] || die "required extension missing: $extension"
  done
fi
if [[ -n "${EMG_EXPECTED_PITR_TARGET_TIME:-}" ]]; then
  [[ "$EMG_EXPECTED_PITR_TARGET_TIME" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || die "unsafe PITR target time"
  replay_ok="$(psql "$EMG_RESTORE_DSN" -XAtqc "SELECT pg_last_xact_replay_timestamp() IS NOT NULL AND pg_last_xact_replay_timestamp() <= '$EMG_EXPECTED_PITR_TARGET_TIME'::timestamptz")"
  [[ "$replay_ok" == t ]] || die "PITR replay time exceeded or did not reach the expected target"
fi
if [[ -n "${EMG_EXPECTED_TIMELINE:-}" ]]; then
  timeline="$(psql "$EMG_RESTORE_DSN" -XAtqc "SELECT timeline_id FROM pg_control_checkpoint()")"
  [[ "$timeline" == "$EMG_EXPECTED_TIMELINE" ]] || die "recovery timeline mismatch"
fi
if [[ -n "${EMG_RECOVERY_ASSERT_SQL:-}" ]]; then
  [[ "$(psql "$EMG_RESTORE_DSN" -XAtqc "$EMG_RECOVERY_ASSERT_SQL")" == t ]] || die "recovery row-level assertion failed"
fi
"$SCRIPT_DIR/invalidate-identity-refresh-state.sh"
"$PYTHON_BIN" "$SCRIPT_DIR/verify-evidence-ledger.py" --dsn "$EMG_RESTORE_DSN" --manifest "$manifest"
