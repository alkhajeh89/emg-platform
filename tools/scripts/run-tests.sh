#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if find libs services -name "test_*.py" 2>/dev/null | grep -q .; then
  pytest
else
  echo "No tests exist yet — unit-tests stage is a no-op (Sprint 1 scaffold)"
fi
