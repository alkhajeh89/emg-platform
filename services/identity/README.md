# services/identity

Module 4 — Identity & Authentication. Sprint 2 implementation of
**FEAT-02-1 (Identity Provider Integration)** and **FEAT-02-2
(Authentication Session Management)**, per Engineering Backlog v1.0 §6
(Sprint 2) and US-02.

## Scope

In scope this sprint:

- Keycloak-backed authentication (Direct Access Grants / resource-owner
  password credentials) against the local-dev realm seeded in
  `tools/seed-data/keycloak/emg-realm.json`.
- EMG-minted session tokens (JWT, HS256 locally): short-lived access token
  + rotating refresh token, independent of Keycloak's own token lifetimes.
- A concrete `AuthClient` implementation (`auth_client.py`) against the
  Protocol shipped in `libs/python/emg-auth-client` (Sprint 1).
- Interim authentication-event logging (`audit.py`) standing in for the
  audit pipeline until FEAT-04-1 (Sprint 5-6) — see "Known Limitations"
  below.

Out of scope this sprint (Sprint 3, per Engineering Backlog v1.0 §6):

- **FEAT-02-3 Service Identity & M2M Auth** — non-human/service-to-service
  authentication (e.g. client-credentials grant for other EMG services).
- **FEAT-02-4 Identity Federation Readiness** — air-gapped/disconnected
  identity provider support.

Also out of scope, by design, for any sprint in this service: authorization
decisions (Module 5 / EPIC-03) and audit storage (Module 6 / EPIC-04) — this
service authenticates and issues sessions; it does not decide *what* an
authenticated principal may do.

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/auth/login` | Exchange username/password for an EMG session (access + refresh token) via Keycloak |
| `POST` | `/auth/refresh` | Exchange a valid refresh token for a new, rotated token pair |
| `GET` | `/auth/session` | Return the authenticated Principal (subject, roles, attributes) for the current Bearer token |
| `GET` | `/healthz` | Liveness/readiness probe |

All error responses use the shared `emg_api_contracts.ApiResponse` envelope;
`emg_errors.AuthorizationError` maps to HTTP 401, `ValidationError` to 400,
`UpstreamServiceError` (Keycloak unreachable) to 502.

## Design Decisions (Sprint 2)

Architecture Baseline v1.0 intentionally leaves some Module 4 implementation
detail open for engineering to refine (Engineering Master Plan §1). This
sprint's concrete choices, and why:

1. **EMG mints its own session token rather than forwarding Keycloak's.**
   Every downstream service depends on one EMG-governed session contract
   (`session.py`) instead of each needing to understand Keycloak's token
   format. The EMG access token carries `roles` and `attributes` matching
   `emg_auth_client.Principal` exactly, so Module 5's Policy Enforcement
   Point (FEAT-03-1) can consume it directly once built — satisfying US-02's
   "token carries the claims Module 5's PEP requires" acceptance criterion
   ahead of Module 5 existing.
2. **Stateless JWT sessions, no session database.** Module 6 (audit/session
   storage) is Sprint 5-6 scope; introducing a bespoke Postgres schema for
   session state now would be schema debt to migrate later. Refresh tokens
   are rotated on every use to limit replay exposure.
3. **Authentication-event logging via `emg_telemetry`, not a real audit
   store.** See "Known Limitations."
4. **User federation (LDAP/AD) is not configured in the local-dev realm.**
   `tools/seed-data/keycloak/emg-realm.json` seeds two local test users only;
   real external identity-provider federation is an environment-specific
   operational configuration applied per deployment (e.g. the Ministry of
   Interior's directory), not something to hardcode into a mock realm.

## Known Limitations (tracked, not silently accepted)

- **No session revocation.** Because there is no persistent session store
  yet, a compromised refresh token cannot be actively revoked before its
  natural expiry (12h default, `EMG_IDENTITY_REFRESH_TOKEN_TTL_SECONDS`).
  Acceptable for Sprint 2's stated acceptance criteria (issuance, refresh,
  expiry — not revocation); revisit when Module 6 lands.
- **`StructuredLogAuditSink` (`audit.py`) is not Module 6.** It emits
  structured log events in the same actor/action/outcome/correlation-id
  shape Module 6's append-only store will expect (ADR-015 §1), so the swap
  to a real audit-pipeline-backed sink in EPIC-04 is a one-line dependency
  change (`dependencies.py`), not a rewrite of any call site.
- **Local-dev secrets in `emg-realm.json` / `config.py` defaults** (client
  secret, JWT signing key, seed user passwords) are placeholders for
  `docker-compose.yml` only, clearly labeled, and must be overridden via the
  centralized secrets store in any non-local environment (Engineering
  Master Plan §5).

## Running Locally

```bash
make up                                   # starts Keycloak (with this realm imported), Postgres, etc.
pip install -e libs/python/emg-common-types -e libs/python/emg-errors \
            -e libs/python/emg-telemetry -e libs/python/emg-auth-client \
            -e libs/python/emg-api-contracts -e services/identity
uvicorn emg_identity.main:app --reload --app-dir services/identity/src
curl -X POST localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "dev.investigator", "password": "dev_local_password_only"}'
```

## Testing

```bash
pytest services/identity/tests
```

Unit tests cover session issuance/verification/expiry/tampering
(`test_session.py`), the Keycloak client's success and failure paths against
a mocked transport (`test_keycloak_client.py`), and the HTTP surface
end-to-end including failed-login audit-log emission
(`test_auth_router.py`).
