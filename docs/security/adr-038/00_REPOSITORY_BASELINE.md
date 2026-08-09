# ADR-038 Capability Verification — Repository Baseline

Recorded at the start of verification work. Read-only reconnaissance; nothing
in this section was modified.

> **Historical evidence only.** The table records `10bd419` before capability
> verification and Phase 2B. Verification and implementation subsequently
> completed; current status is recorded in `ARCHITECTURE_STATUS.md` and
> `06_FINAL_VERIFICATION_REPORT.md`. Statements below that capability was absent
> must not be read as current repository status.

| Item | Value |
| :--- | :--- |
| Branch | `develop` |
| HEAD (start of verification) | `10bd419327e78430782f9bc4687376439fe21096` — "Merge pull request #60 … architecture/adr-038-human-delegation" |
| Keycloak version (shared dev stack) | `quay.io/keycloak/keycloak:25.0` (pinned by digest, `docker-compose.yml`) |
| Shared dev stack, running throughout | `emg-keycloak` (:8080), `emg-identity` (:8001), `emg-audit` (:8002), `emg-postgres`, `emg-redis`, `emg-qdrant`, `emg-neo4j` — **none of these were started, stopped, or modified by this verification** |
| Realm artifacts (both left untouched) | `tools/seed-data/keycloak/emg-realm.json` (realm `emg`, 5 confidential service clients, no human-capable client) and `docker/keycloak/import/emg-realm.json` (realm `emg`, one client `emg-frontend` with `publicClient: true`, unreconciled). Both confirmed still present, byte-identical to the pre-verification baseline. |
| Registered clients (seed realm) | `emg-identity-service`, `emg-svc-identity`, `emg-svc-authorization`, `emg-svc-audit`, `emg-svc-knowledge-graph-writer` — all confidential service accounts, `standardFlowEnabled: false` |
| Existing service-token validation | Independently implemented and tested in `services/knowledge-graph`, `services/audit`, `services/identity` — RS256 + JWKS + issuer + audience + required-claim checks. Real negative coverage already existed (wrong issuer/audience, expired, tampered, missing tenant/roles). |
| tenant_id handling | Verified-claim-only, fail-closed, never client-supplied — consistent across ADR-025/034/035/036/038 and already tested. |
| classification_clearance handling | Flat, closed 4-value `Classification` enum; normalized via one shared helper; fail-closed default `UNCLASSIFIED`; fully wired into every Knowledge Graph route. |
| Audit attribution support | `emg-audit-client`'s `SubmittedAuditEvent`/`AuditEvent` already had everything ADR-038 §8.7/AC-11 needs with **no schema change**: `source_principal` (server-assigned from the verified producer token → Acting Service), `actor`/`actor_type` (producer-supplied → Human Principal), plus `tenant_id`, `classification`, `correlation_id`, open `metadata`. Confirmed usable as-is (see `05_TEST_EXECUTION_LOG.md`). |
| Human-auth / BFF / delegation implementation | **None exists.** `apps/` = `.gitkeep` + README only. No Authorization-Code client in either realm file. `services/identity/src/emg_identity/keycloak_client.py` has `login_with_password` and `client_credentials_token` but no token-exchange method anywhere in the repo. Matches ADR-038's own "Accepted — not implemented" status. |
| Idle branch found | `security/adr-038-capability-verification` existed locally, identical to `develop` (zero commits ahead) — a pre-staged branch name, no prior work to reconcile. |

## Constraint recap (from the approved plan)

- Isolated verification environment only; the shared stack above is never
  touched or depended upon.
- No production Studio BFF, no product functionality.
- No modification of ADR-035, ADR-036, or ADR-038.
- No new ADR.
- No production service-code changes (`services/*` source is read-only
  throughout this verification).
- Keycloak behaviour (claim shape, token-exchange mechanics) determined
  experimentally, never assumed.
- No committed reusable secrets; synthetic credentials injected at runtime.
