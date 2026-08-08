#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
PYTHON_BIN="${EMG_BACKUP_PYTHON:-python3}"
require_command pg_basebackup
require_command python3
: "${EMG_BACKUP_REPOSITORY:?must be an absolute mounted repository}"
: "${EMG_BACKUP_DSN:?must be supplied by the secret store}"
: "${EMG_BACKUP_ENCRYPT_COMMAND:?must be an executable INPUT OUTPUT wrapper}"
: "${EMG_MANIFEST_SIGN_COMMAND:?must be an executable MANIFEST SIGNATURE wrapper}"
: "${EMG_BACKUP_KEY_REFERENCE:?must identify recoverable escrowed key material}"
[[ "$EMG_BACKUP_REPOSITORY" = /* && -d "$EMG_BACKUP_REPOSITORY" ]] || die "invalid backup repository"
backup_id="${EMG_BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
created_at="${EMG_BACKUP_CREATED_AT:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
[[ "$backup_id" =~ ^[A-Za-z0-9._-]+$ ]] || die "unsafe backup id"
staging="$EMG_BACKUP_REPOSITORY/.staging-$backup_id"
final="$EMG_BACKUP_REPOSITORY/full/$backup_id"
[[ ! -e "$staging" && ! -e "$final" ]] || die "backup id already exists"
mkdir -p "$staging/plain"
trap 'rm -rf -- "$staging"' EXIT
pg_basebackup --dbname="$EMG_BACKUP_DSN" --format=tar --gzip --wal-method=stream --checkpoint=fast --manifest-checksums=SHA256 --pgdata="$staging/plain"
while IFS= read -r -d '' input; do
  "$EMG_BACKUP_ENCRYPT_COMMAND" "$input" "$staging/$(basename "$input").enc"
done < <(find "$staging/plain" -maxdepth 1 -type f -print0 | LC_ALL=C sort -z)
"$PYTHON_BIN" "$SCRIPT_DIR/build_manifest.py" --pg-manifest "$staging/plain/backup_manifest" --artifact-directory "$staging" --output "$staging/manifest.json" --backup-id "$backup_id" --created-at "$created_at" --dsn "$EMG_BACKUP_DSN" --key-reference "$EMG_BACKUP_KEY_REFERENCE" --tablespaces-json "${EMG_BACKUP_TABLESPACES_JSON:-[]}"
rm -rf -- "$staging/plain"
"$PYTHON_BIN" "$SCRIPT_DIR/backup_manifest.py" validate "$staging/manifest.json" --verify-files
"$EMG_MANIFEST_SIGN_COMMAND" "$staging/manifest.json" "$staging/manifest.sig"
[[ -s "$staging/manifest.sig" ]] || die "manifest signature was not created"
python3 - "$staging" <<'PY'
import os, pathlib, sys
root=pathlib.Path(sys.argv[1])
for path in root.iterdir():
    if path.is_file():
        with path.open('rb') as stream: os.fsync(stream.fileno())
fd=os.open(root, os.O_RDONLY); os.fsync(fd); os.close(fd)
PY
mkdir -p "$(dirname "$final")"
mv "$staging" "$final"
python3 - "$(dirname "$final")" <<'PY'
import os, sys
fd=os.open(sys.argv[1], os.O_RDONLY); os.fsync(fd); os.close(fd)
PY
trap - EXIT
printf '%s\n' "$final"
