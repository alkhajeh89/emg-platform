#!/usr/bin/env bash
# Generates a throwaway .env.verification.local with random synthetic
# credentials for the ADR-038 non-production verification environment.
# Re-run any time; values are not persisted anywhere else and are never
# committed (see .gitignore in this directory).
set -euo pipefail
cd "$(dirname "$0")"

rand() { openssl rand -hex 24; }

cat > .env.verification.local <<ENV
EMG_VERIFICATION_KC_ADMIN_PASSWORD=$(rand)
EMG_VERIFICATION_HUMAN_A_PASSWORD=$(rand)
EMG_VERIFICATION_HUMAN_B_PASSWORD=$(rand)
EMG_VERIFICATION_ROPC_SECRET=$(rand)
EMG_VERIFICATION_BFF_SECRET=$(rand)
EMG_VERIFICATION_BFF_UNAUTHORIZED_SECRET=$(rand)
EMG_VERIFICATION_KG_WRITER_SECRET=$(rand)
ENV

echo "Wrote $(pwd)/.env.verification.local (gitignored, throwaway)."
