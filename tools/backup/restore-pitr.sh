#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
: "${EMG_BACKUP_REPOSITORY:?must be set}"
[[ $# -ge 3 && $# -le 4 ]] || die "usage: restore-pitr.sh BACKUP_DIR TARGET_DIR TARGET_TIME [promote|pause|shutdown]"
target_time="$3"
action="${4:-promote}"
"$SCRIPT_DIR/restore-full.sh" "$1" "$2"
python3 "$SCRIPT_DIR/backup_manifest.py" pitr-config --target-time "$target_time" \
  --restore-command "$SCRIPT_DIR/restore-wal.sh" --action "$action" >>"$2/postgresql.auto.conf"
touch "$2/recovery.signal"
printf 'PITR restore prepared for %s; start PostgreSQL under recovery supervision\n' "$target_time"
