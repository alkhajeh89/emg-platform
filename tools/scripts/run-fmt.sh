#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if find libs services -name "*.py" 2>/dev/null | grep -q .; then
  ruff check --fix libs services
  black libs services
else
  echo "No Python sources yet — format is a no-op"
fi
