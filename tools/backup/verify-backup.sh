#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${EMG_MANIFEST_VERIFY_COMMAND:?must be an executable MANIFEST SIGNATURE wrapper}"
[[ $# -eq 1 ]] || { echo "usage: verify-backup.sh MANIFEST" >&2; exit 2; }
manifest="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
"$EMG_MANIFEST_VERIFY_COMMAND" "$manifest" "$(dirname "$manifest")/manifest.sig"
exec python3 "$SCRIPT_DIR/backup_manifest.py" validate "$manifest" --verify-files
