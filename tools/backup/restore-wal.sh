#!/usr/bin/env bash
set -euo pipefail
: "${EMG_BACKUP_REPOSITORY:?must be set}"
: "${EMG_BACKUP_DECRYPT_COMMAND:?must be set}"
[[ $# -eq 2 ]] || { echo "usage: restore-wal.sh WAL_FILENAME DESTINATION" >&2; exit 2; }
[[ "$1" =~ ^([0-9A-F]{24}|[0-9A-F]{8}\.history|[0-9A-F]{24}\.[0-9A-F]{8}\.backup)$ ]] || { echo "invalid WAL/history filename" >&2; exit 2; }
source_file="$EMG_BACKUP_REPOSITORY/wal/$1.enc"
metadata="$source_file.integrity.json"
[[ -f "$source_file" && -f "$metadata" ]] || { echo "WAL artifact or integrity metadata missing" >&2; exit 1; }
python3 - "$source_file" "$metadata" <<'PY'
import hashlib,json,os,sys
p,m=sys.argv[1:]
d=json.load(open(m,encoding='utf-8'))
if d.get('cipherSha256') != hashlib.sha256(open(p,'rb').read()).hexdigest() or d.get('size') != os.path.getsize(p): raise SystemExit(1)
PY
temporary="$2.tmp.$$"
trap 'rm -f -- "$temporary"' EXIT
"$EMG_BACKUP_DECRYPT_COMMAND" "$source_file" "$temporary"
python3 - "$temporary" "$metadata" <<'PY'
import hashlib,json,sys
if hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()!=json.load(open(sys.argv[2],encoding='utf-8'))['plainSha256']: raise SystemExit(1)
PY
mv "$temporary" "$2"
trap - EXIT
