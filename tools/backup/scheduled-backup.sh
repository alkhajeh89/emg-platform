#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
: "${EMG_BACKUP_REPOSITORY:?must be an absolute mounted repository}"
: "${EMG_MANIFEST_VERIFY_COMMAND:?must be an executable MANIFEST SIGNATURE wrapper}"

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
started_epoch="$(date -u +%s)"
backup_id="${EMG_BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
evidence_dir="$EMG_BACKUP_REPOSITORY/recovery-evidence"
mkdir -p "$evidence_dir"

failure() {
  code=$?
  printf '{"event":"emg.recovery.backup.failed","backupId":"%s","startedAt":"%s","exitCode":%d}\n' \
    "$backup_id" "$started_at" "$code" >&2
  exit "$code"
}
trap failure ERR

export EMG_BACKUP_ID="$backup_id"
backup_dir="$("$SCRIPT_DIR"/full-backup.sh | tail -n 1)"
"$SCRIPT_DIR/verify-backup.sh" "$backup_dir/manifest.json"
completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
duration="$(( $(date -u +%s) - started_epoch ))"
temporary="$evidence_dir/.${backup_id}.json.tmp"
printf '{"schemaVersion":1,"event":"emg.recovery.backup.verified","backupId":"%s","startedAt":"%s","completedAt":"%s","durationSeconds":%d,"manifest":"full/%s/manifest.json"}\n' \
  "$backup_id" "$started_at" "$completed_at" "$duration" "$backup_id" >"$temporary"
mv "$temporary" "$evidence_dir/${backup_id}.json"
trap - ERR
cat "$evidence_dir/${backup_id}.json"
