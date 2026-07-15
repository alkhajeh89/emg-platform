#!/usr/bin/env bash
# Scaffolding generator: creates a new backend service directory following
# the standard layout used by /services/* (Module 1 repository structure).
#
# Usage: ./tools/scripts/new-service.sh <service-name>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <service-name>" >&2
  exit 1
fi

NAME="$1"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="$ROOT_DIR/services/$NAME"

if [ -d "$SERVICE_DIR" ]; then
  echo "services/$NAME already exists" >&2
  exit 1
fi

mkdir -p "$SERVICE_DIR/src" "$SERVICE_DIR/tests"
touch "$SERVICE_DIR/src/.gitkeep" "$SERVICE_DIR/tests/.gitkeep"

cat > "$SERVICE_DIR/README.md" << EOR
# services/$NAME

Scaffolded by tools/scripts/new-service.sh. Fill in service.yaml ownership
metadata and implement per the governing module's approved contract. Do not
introduce business logic here until the owning Epic/Feature's sprint begins.
EOR

cat > "$SERVICE_DIR/service.yaml" << EOR
name: $NAME
owner: TBD            # Accountable Owner per ADR-016 Section 1
steward: TBD           # Operational Steward per ADR-016 Section 1
module: TBD             # Governing Module (4-10)
status: scaffolded
EOR

echo "Created services/$NAME"
