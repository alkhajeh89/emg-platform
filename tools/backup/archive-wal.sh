#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh disable=SC1091
source "$SCRIPT_DIR/common.sh"
: "${EMG_BACKUP_REPOSITORY:?must be set}"
: "${EMG_BACKUP_ENCRYPT_COMMAND:?must be set}"
[[ $# -eq 2 ]] || die "usage: archive-wal.sh SOURCE_PATH WAL_FILENAME"
[[ "$2" =~ ^([0-9A-F]{24}|[0-9A-F]{8}\.history|[0-9A-F]{24}\.[0-9A-F]{8}\.backup)$ ]] || die "invalid WAL/history filename"
[[ -f "$1" ]] || die "WAL source is missing"
mkdir -p "$EMG_BACKUP_REPOSITORY/wal"
destination="$EMG_BACKUP_REPOSITORY/wal/$2.enc"
metadata="$destination.integrity.json"
plain_sha="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1")"
if [[ -e "$destination" || -e "$metadata" ]]; then
  [[ -f "$destination" && -f "$metadata" ]] || die "partial existing WAL archive"
  python3 - "$destination" "$metadata" "$plain_sha" <<'PY'
import hashlib,json,sys
p,m,plain=sys.argv[1:]
d=json.load(open(m,encoding='utf-8'))
c=hashlib.sha256(open(p,'rb').read()).hexdigest()
if d != {'cipherSha256':c,'plainSha256':plain,'size':__import__('os').path.getsize(p)}: raise SystemExit(1)
PY
  exit 0
fi
temporary="$destination.tmp.$$"
meta_tmp="$metadata.tmp.$$"
trap 'rm -f -- "$temporary" "$meta_tmp"' EXIT
"$EMG_BACKUP_ENCRYPT_COMMAND" "$1" "$temporary"
[[ -s "$temporary" ]] || die "encrypted WAL is empty"
python3 - "$temporary" "$meta_tmp" "$plain_sha" <<'PY'
import hashlib,json,os,sys
p,o,plain=sys.argv[1:]
d={'cipherSha256':hashlib.sha256(open(p,'rb').read()).hexdigest(),'plainSha256':plain,'size':os.path.getsize(p)}
open(o,'w',encoding='utf-8').write(json.dumps(d,sort_keys=True)+'\n')
for f in (p,o):
 s=open(f,'rb'); os.fsync(s.fileno()); s.close()
PY
chmod 0600 "$temporary" "$meta_tmp"
mv "$temporary" "$destination"
mv "$meta_tmp" "$metadata"
python3 - "$(dirname "$destination")" <<'PY'
import os,sys
fd=os.open(sys.argv[1],os.O_RDONLY); os.fsync(fd); os.close(fd)
PY
trap - EXIT
