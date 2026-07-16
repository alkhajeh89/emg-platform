# services/audit

Module 6 — Enterprise Audit, Provenance & Digital Evidence Platform.

- **Sprint 6:** **FEAT-04-1 (Audit Event Pipeline)** — activated as a minimal
  live service (previously scaffolded). Per Engineering Backlog v1.0 §6 and
  US-04.
- **Sprint 7:** **FEAT-04-2 (Provenance Record Model)** + **FEAT-04-3 (Digital
  Evidence Chain-of-Custody)** — optional versioned provenance on audit events
  (version-aware hashing keeps every Sprint 6 record byte-for-byte verifiable)
  and a separate append-only custody ledger with tamper/gap detection.
  **FEAT-04-4 (Audit Query & Reporting Interface) is deferred to the immediate
  next sprint**; EPIC-04 remains incomplete until it lands. See
  `docs/engineering/sprint-7-design.md`.

This service is a **thin deployment shell** over the shared audit libraries:
all audit logic (the `AuditEvent`/`ProvenanceRecord`/`CustodyEvent` models,
append-only stores, canonical hashing, centralized hash chains + sequencing,
integrity verification, idempotency, redaction) lives in
`libs/python/emg-audit-client` (contract) and `libs/python/emg-audit-pipeline`
(implementation). See `docs/engineering/sprint-6-design.md` and
`docs/engineering/sprint-7-design.md`.

## Scope (Sprint 6)

In scope: authenticated ingestion of governed-action audit events; the single
append-only store (PostgreSQL tier-1, in-memory for tests); the minimal US-04
query (by actor, time range, correlation id); hash-chain integrity
verification; and health/readiness reporting that surfaces store degradation.

## Scope (Sprint 7 — FEAT-04-2 + FEAT-04-3)

Added: an optional versioned `ProvenanceRecord` on ingested audit events
(server-assigned event `schema_version`; version-1 events remain byte-for-byte
hash-compatible with Sprint 6), and a **separate append-only chain-of-custody
ledger** with a global hash chain, per-evidence custody sequence, and tamper /
deletion / gap detection.

Out of scope (immediate next sprint, deliberately): **FEAT-04-4 (Audit Query &
Reporting Interface)** — the richer human/classification-aware reporting surface.
EPIC-04 remains incomplete until FEAT-04-4 is delivered, and EPIC-05 (Module 7)
is blocked until then. No new roles, no new ADR, no UI.

## API

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/audit/events` | any recognized service principal | Ingest one audit event (idempotent by `event_id`). Optionally carries `provenance` (→ schema-version-2). The store assigns sequence + hash chain. |
| `GET` | `/audit/events` | `svc-audit` role | Minimal query by `actor`, `start_time`/`end_time`, `correlation_id`, `limit`. |
| `GET` | `/audit/integrity` | `svc-audit` role | Recompute and verify the audit hash chain (out-of-band mutation detection). |
| `POST` | `/audit/custody/events` | `svc-audit` role | Record one custody transfer (append-only, idempotent by `(source_principal, custody_event_id)`). The store assigns global + per-evidence sequence and the hash chain. |
| `GET` | `/audit/custody/events` | `svc-audit` role | Query the custody ledger by `evidence_id`, `custodian`, time range, `limit`. |
| `GET` | `/audit/custody/integrity` | `svc-audit` role | Verify the custody hash chain and per-evidence sequence contiguity (tamper / deletion / gap detection). |
| `GET` | `/healthz` | none | Liveness. |
| `GET` | `/readyz` | none | Readiness: reports store backend and availability (`degraded` if the store is unreachable). |

Custody endpoints are least-privilege and service-authenticated, restricted to
the existing `svc-audit` role — no new role, no human/UI access (that is
FEAT-04-4).

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

Neither the audit store nor the custody ledger exposes an update or delete
path. The PostgreSQL application role (`emg_audit_app`) is granted **INSERT and
SELECT only** on both `audit_events` (`001_audit_events.sql`) and
`evidence_custody_events` (`003_evidence_custody.sql`); `002_audit_provenance.sql`
adds provenance columns additively without rewriting any existing row. "No
mutation or deletion" is therefore an application- and database-role guarantee —
**not** an absolute claim that a PostgreSQL superuser (or direct storage access)
can never alter bytes. The hash-chain integrity verifications (`GET
/audit/integrity`, `GET /audit/custody/integrity`) are the compensating controls
that *detect* any such out-of-band mutation, deletion, or sequence gap.

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
