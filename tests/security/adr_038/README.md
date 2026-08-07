# ADR-038 Non-Production Capability Verification

This directory is the mandatory, non-production capability verification for
ADR-038 (Human Identity Delegation Architecture) — the verification *gate*,
not Phase 2B implementation. See `docs/security/adr-038/` for the full
report, capability matrix, and experimental findings.

It is fully isolated from the shared development stack (`docker-compose.yml`
at the repo root): separate Docker Compose project, network, container name,
port (`8180`, not `8080`), and Keycloak realm (`emg-verification`, not
`emg`). It never starts, stops, or modifies the shared stack, and it holds
no product code.

## Running

```bash
cd tests/security/adr_038
./generate_env.sh                 # first run only — generates throwaway synthetic secrets
pytest .                          # brings the environment up, provisions it, runs all 25 tests, tears down
```

Set `EMG_VERIFICATION_KEEP_UP=1` to leave the isolated Keycloak container
running after the test session (useful for interactive debugging or running
subsets of the suite without re-provisioning each time):

```bash
EMG_VERIFICATION_KEEP_UP=1 pytest tests/security/adr_038/test_negative_delegation.py -v
```

To tear down manually:

```bash
docker compose --env-file .env.verification.local -f docker-compose.verification.yml down -v
```

## Files

| File | Purpose |
| :--- | :--- |
| `docker-compose.verification.yml` | Isolated Keycloak 25 container, its own network/port/volume. |
| `realm/emg-verification-realm.json` | Declarative realm import — no secrets committed (see below). |
| `generate_env.sh` | Generates `.env.verification.local` (gitignored) with random synthetic credentials. |
| `provision.py` | Idempotent post-import Admin REST API steps: regenerates every client secret, sets human test-user passwords, grants fine-grained token-exchange permission to the authorized test BFF only. |
| `keycloak_client.py` | Thin HTTP wrapper for the OAuth token endpoint (ROPC, client-credentials, token-exchange, refresh). |
| `claim_adapter.py` | The ONE place that knows Keycloak's raw claim shape (`azp` = Acting Service); maps to the technology-neutral `DelegatedCredential`. |
| `downstream_validator.py` | Per-audience independent validator, mirroring production's `TenantServiceTokenValidator` contract. |
| `audit_harness.py` | Real, unmodified `emg_audit_service` app + isolated in-process test persistence — never touches the shared `emg-audit` container. |
| `conftest.py` | Session fixture: bring-up, health-wait, provision, teardown. |
| `test_positive_delegation.py` | Phase 5 — 10 positive capability tests. |
| `test_negative_delegation.py` | Phase 6 — 11 required fail-closed scenarios. |
| `test_credential_lifetime.py` | Phase 7 — configured lifetime, reuse-cannot-extend proofs. |
| `test_audit_attribution.py` | Complete audit attribution, integration-level. |

## Secret hygiene

No committed file contains a usable secret. `realm/emg-verification-realm.json`
declares clients/users with no `secret`/`credentials` fields at all —
Keycloak auto-generates placeholders on import, and `provision.py`
immediately regenerates every one via the Admin REST API, writing the real
values only to `.env.verification.local` (gitignored, never committed).
`docker-compose.verification.yml` requires every credential via
`${VAR:?...}` — it refuses to start without that file.
