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
require_recovery_authorization() {
  [[ "${EMG_RECOVERY_MODE:-}" == "isolated-restore" ]] || die "EMG_RECOVERY_MODE must be isolated-restore"
  [[ "${EMG_RECOVERY_CONFIRMATION:-}" == "RESTORE_INTO_EMPTY_TARGET" ]] || die "explicit restore confirmation is required"
  [[ -n "${EMG_RECOVERY_TARGET_ID:-}" ]] || die "EMG_RECOVERY_TARGET_ID must identify the isolated target"
  [[ "${EMG_RECOVERY_TARGET_ID}" =~ ^[A-Za-z0-9._-]+$ ]] || die "unsafe recovery target identifier"
  [[ "${EMG_RECOVERY_TARGET_ID}" != "production" ]] || die "active production is not a valid restore target"
}
