#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
require_command python3
require_command tar
: "${EMG_BACKUP_DECRYPT_COMMAND:?must be an executable INPUT OUTPUT wrapper}"
: "${EMG_MANIFEST_VERIFY_COMMAND:?must be an executable MANIFEST SIGNATURE wrapper}"
[[ $# -eq 2 ]] || die "usage: restore-full.sh BACKUP_DIRECTORY TARGET_DATA_DIRECTORY"
require_recovery_authorization
backup_dir="$(cd "$1" && pwd)"
target="$2"
require_empty_directory "$target" TARGET_DATA_DIRECTORY
"$EMG_MANIFEST_VERIFY_COMMAND" "$backup_dir/manifest.json" "$backup_dir/manifest.sig"
python3 "$SCRIPT_DIR/backup_manifest.py" validate "$backup_dir/manifest.json" --verify-files
temporary="$target/.restore"
mkdir "$temporary"
trap 'rm -rf -- "$temporary"' EXIT
while IFS=$'\t' read -r role path oid destination; do
  output="$temporary/${path%.enc}"
  "$EMG_BACKUP_DECRYPT_COMMAND" "$backup_dir/$path" "$output"
  case "$role" in
    base) base_archive="$output" ;;
    wal) wal_archive="$output" ;;
    postgres-manifest) [[ -s "$output" ]] || die "PostgreSQL manifest is empty" ;;
    tablespace)
      [[ "$destination" = /* && "$destination" != "$target"* ]] || die "unsafe tablespace destination for $oid"
      printf '%s\t%s\t%s\n' "$oid" "$destination" "$output" >>"$temporary/tablespaces.tsv"
      ;;
    *) die "unconsumed artifact role: $role" ;;
  esac
done < <(python3 - "$backup_dir/manifest.json" <<'PY'
import json, sys
m=json.load(open(sys.argv[1], encoding='utf-8'))
dest={x['oid']:x['restorePath'] for x in m['tablespaces']}
for a in m['artifacts']:
 print(a['role'], a['path'], a.get('tablespaceOid','-'), dest.get(a.get('tablespaceOid',''),'-'), sep='\t')
PY
)
: "${base_archive:?manifest did not produce a base archive}"
: "${wal_archive:?manifest did not produce a WAL archive}"
tar -xzf "$base_archive" -C "$target"
mkdir -p "$target/pg_wal"
tar -xzf "$wal_archive" -C "$target/pg_wal"
if [[ -f "$temporary/tablespaces.tsv" ]]; then
  while IFS=$'\t' read -r oid destination archive; do
    mkdir -p "$destination"
    require_empty_directory "$destination" TABLESPACE_DESTINATION
    tar -xzf "$archive" -C "$destination"
    link="$target/pg_tblspc/$oid"
    [[ ! -e "$link" || -L "$link" ]] || die "tablespace link target is not a symlink"
    rm -f -- "$link"
    ln -s "$destination" "$link"
  done <"$temporary/tablespaces.tsv"
fi
[[ -f "$target/PG_VERSION" ]] || die "restored cluster lacks PG_VERSION"
[[ -f "$target/backup_label" ]] || die "restored cluster lacks backup_label"
[[ -d "$target/global" && -d "$target/base" && -d "$target/pg_wal" ]] || die "restored cluster structure is incomplete"
rm -rf -- "$temporary"
trap - EXIT
chmod 0700 "$target"
printf 'full restore prepared at %s; PostgreSQL has not been started\n' "$target"
