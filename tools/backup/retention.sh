#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
: "${EMG_BACKUP_REPOSITORY:?must be set}"
: "${EMG_RETENTION_NOW:?must be canonical UTC and within 24 hours of system time}"
days="${EMG_RETENTION_MINIMUM_DAYS:-35}"
count="${EMG_RETENTION_MINIMUM_COUNT:-2}"
make_plan() { python3 "$SCRIPT_DIR/backup_manifest.py" retention-plan --repository "$EMG_BACKUP_REPOSITORY/full" --now "$EMG_RETENTION_NOW" --minimum-days "$days" --minimum-count "$count"; }
plan="$(make_plan)"
if [[ "${1:-}" != "--apply" ]]; then
  printf '%s\n' "$plan"
  exit 0
fi
[[ $# -eq 2 && "$2" =~ ^[a-f0-9]{64}$ ]] || die "usage: retention.sh --apply REVIEWED_PLAN_ID"
actual_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["planId"])' <<<"$plan")"
[[ "$2" == "$actual_id" ]] || die "repository state or reviewed plan changed"
python3 -c 'import json,sys; [print(x) for x in json.load(sys.stdin)["delete"]]' <<<"$plan" |
while IFS= read -r candidate; do
  [[ "$candidate" == "$EMG_BACKUP_REPOSITORY/full/"* ]] || die "candidate escaped repository"
  python3 "$SCRIPT_DIR/backup_manifest.py" validate "$candidate/manifest.json" --verify-files
  rm -rf -- "$candidate"
done
