# services/audit

Module 6 — Enterprise Audit, Provenance & Digital Evidence Platform.

- **Sprint 6:** **FEAT-04-1 (Audit Event Pipeline)** — activated as a minimal
  live service (previously scaffolded). Per Engineering Backlog v1.0 §6 and
  US-04.

This service is a **thin deployment shell** over the shared audit libraries:
all audit logic (the `AuditEvent` model, append-only stores, canonical
hashing, centralized hash chain + sequencing, integrity verification,
idempotency, redaction) lives in `libs/python/emg-audit-client` (contract) and
`libs/python/emg-audit-pipeline` (implementation). See
`docs/engineering/sprint-6-design.md`.

## Scope (Sprint 6)

In scope: authenticated ingestion of governed-action audit events; the single
append-only store (PostgreSQL tier-1, in-memory for tests); the minimal US-04
query (by actor, time range, correlation id); hash-chain integrity
verification; and health/readiness reporting that surfaces store degradation.

Out of scope (later Audit sprints, deliberately): FEAT-04-2 (Provenance Record
Model), FEAT-04-3 (Digital Evidence Chain-of-Custody), and the full FEAT-04-4
(Audit Query & Reporting Interface) — including human compliance-reporting
access. Sprint 6 implements only the minimal query US-04 explicitly requires.

## API

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/audit/events` | any recognized service principal | Ingest one audit event (idempotent by `event_id`). The store assigns sequence + hash chain. |
| `GET` | `/audit/events` | `svc-audit` role | Minimal query by `actor`, `start_time`/`end_time`, `correlation_id`, `limit`. |
| `GET` | `/audit/integrity` | `svc-audit` role | Recompute and verify the hash chain (out-of-band mutation detection). |
| `GET` | `/healthz` | none | Liveness. |
| `GET` | `/readyz` | none | Readiness: reports store backend and availability (`degraded` if the store is unreachable). |

All error responses use the shared `emg_api_contracts.ApiResponse` envelope;
`AuthorizationError` → 401, `ValidationError` (e.g. sensitive metadata key) →
400, request-body schema violations → 422.

## Authentication & authorization

Inbound service tokens are validated independently by this service (Sprint 3
principle: each service validates its own inbound tokens, no shared broker),
using the same Keycloak RS256/JWKS trust path as `services/identity`. **No new
roles are invented** — recognized clients and roles mirror the existing realm
seed (`svc-identity`, `svc-authorization`, `svc-audit`, `service-account`).
Ingestion is open to any recognized EMG service; query and integrity are
restricted to a principal holding `svc-audit`.

## Append-only & integrity

The store exposes no update or delete path. The PostgreSQL application role
(`emg_audit_app`, created by `tools/seed-data/postgres/001_audit_events.sql`)
is granted **INSERT and SELECT only**. "No mutation or deletion" is therefore
an application- and database-role guarantee — **not** an absolute claim that a
PostgreSQL superuser (or direct storage access) can never alter bytes. The
hash-chain integrity verification (`GET /audit/integrity`) is the compensating
control that *detects* any such out-of-band mutation.

## Configuration

All prefixed `EMG_AUDIT_` (see `config.py`); local-dev defaults match
`docker-compose.yml` and must be overridden per environment from the
centralized secrets store for anything secret-shaped.

| Variable | Default (local dev) | Purpose |
| --- | --- | --- |
| `EMG_AUDIT_STORE_BACKEND` | `memory` | `memory` (tests/local) or `postgres` (tier-1). |
| `EMG_AUDIT_POSTGRES_DSN` | *(local-dev placeholder)* | DSN for the append-only store; uses the INSERT/SELECT-only `emg_audit_app` role. |
| `EMG_AUDIT_KEYCLOAK_BASE_URL` | `http://localhost:8080` | Keycloak base URL (token issuer/JWKS). |
| `EMG_AUDIT_KEYCLOAK_REALM` | `emg` | Keycloak realm. |
| `EMG_AUDIT_SERVICE_TOKEN_AUDIENCE` | `emg-internal-services` | Expected `aud` on inbound service tokens. |
| `EMG_AUDIT_JWKS_CACHE_TTL_SECONDS` | `300` | JWKS cache lifespan. |

## Known limitations (Sprint 6)

See `docs/engineering/security-limitations.md` for the consolidated list —
including the superuser/immutability caveat, single-node store, plain init SQL
(no Alembic yet), and the degraded-mode compatibility posture.

## Testing

```bash
pytest services/audit/tests
```

Tests use the in-memory store and an injected local RSA keypair validator — no
Docker or live Keycloak required.
