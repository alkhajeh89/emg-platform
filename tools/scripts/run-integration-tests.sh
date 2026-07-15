#!/usr/bin/env bash
# Integration test entry point. Sprint 1: skeleton only — verifies local
# orchestration (docker-compose) reaches a healthy state. Services register
# their own integration suites here as they land (starting EPIC-02).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

echo "==> Checking local orchestration health"
docker compose ps

echo "==> No service integration suites registered yet (Sprint 1 scaffold) — pass"
