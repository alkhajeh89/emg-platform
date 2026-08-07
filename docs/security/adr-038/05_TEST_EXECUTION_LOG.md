# ADR-038 Capability Verification — Test Execution Log

## Environment bring-up (original run)

```bash
cd tests/security/adr_038
./generate_env.sh
docker compose --env-file .env.verification.local -f docker-compose.verification.yml up -d
python3 provision.py
```

Result: `emg-adr038-verification-keycloak` healthy on `:8180`, isolated
network `emg-adr038-verification-net`, realm `emg-verification` imported,
all client secrets regenerated, both human test-user passwords set,
fine-grained token-exchange permission granted to `emg-verification-bff`
only.

## Resumed session — reconnaissance before continuing

```bash
git status --short
find docs/security/adr-038 -type f
find tests/security/adr_038 -type f
docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}"
docker compose ls
```

Confirmed: `emg-adr038-verification-keycloak` still `Up 3 hours (healthy)`
on `:8180`; all Phase 2/3/4/5 artifacts and the (already-complete, only
mis-tagged as in-progress) Phase 6 negative-test file present; Phase 7
(`test_credential_lifetime.py`) and all `docs/security/adr-038/*` not yet
created. Environment was reused, not recreated.

## Test execution (this session, real infrastructure, `EMG_VERIFICATION_KEEP_UP=1` throughout to avoid tearing down between runs)

```bash
source .venv/bin/activate
export EMG_VERIFICATION_KEEP_UP=1

pytest tests/security/adr_038/test_positive_delegation.py -v
# => 10 passed in 19.16s

pytest tests/security/adr_038/test_negative_delegation.py -v
# => 11 passed, 1 warning in 81.53s (0:01:21)  -- test_7's real ~60s expiry wait dominates

pytest tests/security/adr_038/test_audit_attribution.py -v
# => 1 passed, 1 warning in 18.83s

# Phase 7 file written this session, then run:
pytest tests/security/adr_038/test_credential_lifetime.py -v
# => 3 passed in 20.84s

# Full combined run, all 25 tests together:
pytest tests/security/adr_038/ -v --tb=short
# => 25 passed, 1 warning in 84.38s (0:01:24)
```

All test counts and statuses above are copied verbatim from real pytest
output produced in this session; none are narrated or assumed.

## Ad hoc experimental probes (not pytest — used to populate `02_KEYCLOAK_VERIFICATION_CONFIG.md` with exact evidence)

```bash
# Decode real issued claims (human token + exchanged credential) to confirm
# azp-not-act and sub-preservation:
python3 -c '<inline script using keycloak_client.ropc_login + token_exchange + jwt.decode(verify_signature=False)>'
# => confirmed azp="emg-verification-bff" carries Acting Service; no "act" claim present.

# Confirm re-exchange-of-a-delegated-credential outcome:
python3 -c '<inline script chaining token_exchange(subject_token=<already-exchanged token>)>'
# => HTTP 400 {"error": "invalid_token", "error_description": "Invalid token"}
```

## Final state at end of session

- `emg-adr038-verification-keycloak` left running (healthy) pending
  architecture-review sign-off, so re-running any test or re-inspecting the
  environment interactively remains possible without re-provisioning.
  Teardown command, to run after review: `docker compose --env-file
  .env.verification.local -f tests/security/adr_038/docker-compose.verification.yml
  down -v` (from `tests/security/adr_038/`).
- Shared dev stack (`emg-keycloak`, `emg-audit`, etc.) — unchanged,
  untouched, still running independently throughout.
- No `git add` / `git commit` / `git push` performed at any point in this
  session, per instruction.
