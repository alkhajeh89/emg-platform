#!/usr/bin/env bash
set -euo pipefail
umask 077

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }
require_absolute_directory() {
  [[ "$1" = /* ]] || die "$2 must be an absolute path"
  [[ -d "$1" ]] || die "$2 is not a directory: $1"
}
require_empty_directory() {
  require_absolute_directory "$1" "$2"
  [[ -z "$(find "$1" -mindepth 1 -maxdepth 1 -print -quit)" ]] || die "$2 must be empty"
}
