# services/identity

Module 4 — Identity & Authentication.

- **Sprint 2:** **FEAT-02-1 (Identity Provider Integration)** and
  **FEAT-02-2 (Authentication Session Management)**.
- **Sprint 3:** **FEAT-02-3 (Service Identity & Machine-to-Machine
  Authentication)** and **FEAT-02-4 (Identity Federation Readiness)**.

Per Engineering Backlog v1.0 §6 (Sprints 2-3) and US-02.

## Scope

In scope (Sprint 2):

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

In scope (Sprint 3):

- **OAuth 2.0 Client Credentials (M2M) authentication.** `KeycloakClient
  .client_credentials_token()` for outbound calls; `ServiceTokenValidator`
  for inbound validation of RS256 Keycloak service-account tokens (JWKS,
  issuer, audience, expiry, registered-client, and optional scope checks).
  See `docs/engineering/service-identity-registration.md`.
- **Representative service identities** for the Identity, Authorization, and
  Audit services (`service_registry.py`,
  `tools/seed-data/keycloak/emg-realm.json`) — registration only, no
  downstream service business logic.
- **Structural human/machine separation.** `ServicePrincipal` is a distinct
  type from `Principal`; service tokens (RS256/JWKS) and human session
  tokens (HS256, this service's own key) are cryptographically unrelated
  trust paths. See `docs/engineering/security-limitations.md`.
- **Identity federation readiness** (`federation.py`): a provider-agnostic
  configuration schema and validator for LDAP/Active Directory/external
  OIDC/SAML readiness, air-gapped-safe defaults, and claim/group-to-role
  mapping projection — no external directory is connected. See
  `docs/engineering/federation-readiness.md`.
- **Rate-limiting readiness** for `/auth/login` (`rate_limit.py`).
- **Secret redaction** utility (`redact.py`), applied to the
  `/federation/providers` response and available as a logging backstop.

Also out of scope, by design, for any sprint in this service: authorization
decisions (Module 5 / EPIC-03), audit storage (Module 6 / EPIC-04), user
administration/organization/tenant management, and any Sprint 4+ work — this
service authenticates and issues sessions/service tokens; it does not decide
*what* an authenticated principal may do.

## API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/auth/login` | Exchange username/password for an EMG session (access + refresh token) via Keycloak |
| `POST` | `/auth/refresh` | Exchange a valid refresh token for a new, rotated token pair |
| `GET` | `/auth/session` | Return the authenticated Principal (subject, roles, attributes) for the current Bearer token |
| `GET` | `/auth/service-session` | Return the authenticated `ServicePrincipal` (client_id, service_name, roles, scopes) for the current Bearer *service* token (Sprint 3) |
| `GET` | `/federation/providers` | List configured federation providers, with secret-shaped connection settings redacted (Sprint 3) |
| `GET` | `/federation/health` | Federation configuration validation status (Sprint 3) |
| `GET` | `/healthz` | Liveness/readiness probe |

All error responses use the shared `emg_api_contracts.ApiResponse` envelope;
`emg_errors.AuthorizationError` maps to HTTP 401, `ValidationError` to 400,
`UpstreamServiceError` (Keycloak unreachable) to 502, and (Sprint 3)
`RateLimitedError` to 429.

There is no `POST /auth/service-token` issuance endpoint — see "Why the
identity service does not broker M2M tokens" in
`routers/service_auth.py`'s module docstring and
`docs/engineering/service-identity-registration.md`.

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

## Design Decisions (Sprint 3)

5. **Cryptographic, not flag-based, human/machine separation.** Service
   tokens are Keycloak-issued RS256, verified via the realm's JWKS endpoint;
   human EMG session tokens remain HS256, signed with this service's own
   key. `jwt.decode(..., algorithms=[...])` makes presenting one where the
   other is expected fail at signature verification, before any claim is
   even read — a stronger, more auditable property than a `token_type`
   field a caller could forget to check. See
   `service_token_validator.py`'s module docstring.
6. **The identity service does not broker M2M tokens for other services.**
   Each service holds and uses only its own Keycloak client credentials.
   Brokering would require the identity service to hold every other
   service's secret — a least-privilege violation. See
   `routers/service_auth.py`'s module docstring.
7. **A code-based (not database-based) service registry.**
   `SERVICE_REGISTRY` in `service_registry.py` is the identity service's own
   allow-list of recognized `client_id`s, re-validated independently of
   Keycloak's own signature check. Registering a service is a reviewed
   source change in two files (this registry plus the realm seed), per
   `docs/engineering/service-identity-registration.md`.
8. **Federation is a configuration-and-validation abstraction, not a
   protocol client.** `federation.py` never imports an LDAP/AD/OIDC/SAML
   client library; real directory connectivity is Keycloak's own User
   Federation / Identity Brokering, configured per deployment. See
   `docs/engineering/federation-readiness.md`.

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
- **(Sprint 3) `InMemoryRateLimiter` is readiness, not a production
  control** — single-process, resets on restart. See
  `docs/engineering/security-limitations.md`.
- **(Sprint 3) Federation is validation/configuration readiness only** — no
  LDAP/AD/OIDC/SAML client is invoked by this service. See
  `docs/engineering/federation-readiness.md`.

See `docs/engineering/security-limitations.md` for the full, consolidated
list across Sprint 2 and Sprint 3.

## Environment Variables

All are prefixed `EMG_IDENTITY_` (see `config.py`); local-dev defaults below
match `docker-compose.yml`/`emg-realm.json` and must be overridden per
environment via the centralized secrets store for anything secret-shaped.

| Variable | Default (local dev) | Purpose |
| --- | --- | --- |
| `EMG_IDENTITY_KEYCLOAK_BASE_URL` | `http://localhost:8080` | Keycloak base URL |
| `EMG_IDENTITY_KEYCLOAK_REALM` | `emg` | Keycloak realm |
| `EMG_IDENTITY_KEYCLOAK_CLIENT_ID` | `emg-identity-service` | Human-login confidential client (FEAT-02-1) |
| `EMG_IDENTITY_KEYCLOAK_CLIENT_SECRET` | *(local-dev placeholder)* | Secret for the above client — **never a real value outside `docker-compose.yml`** |
| `EMG_IDENTITY_SESSION_SIGNING_KEY` | *(local-dev placeholder)* | HS256 key for EMG session tokens — **must be overridden in every non-local environment** |
| `EMG_IDENTITY_SESSION_SIGNING_ALGORITHM` | `HS256` | EMG session token signing algorithm |
| `EMG_IDENTITY_ACCESS_TOKEN_TTL_SECONDS` | `900` | EMG access token TTL |
| `EMG_IDENTITY_REFRESH_TOKEN_TTL_SECONDS` | `43200` | EMG refresh token TTL |
| `EMG_IDENTITY_TOKEN_ISSUER` | `emg-identity-service` | EMG session token `iss` claim |
| `EMG_IDENTITY_TOKEN_AUDIENCE` | `emg-platform` | EMG session token `aud` claim |
| `EMG_IDENTITY_SERVICE_CLIENT_ID` (Sprint 3) | `emg-svc-identity` | This service's own outbound M2M client_id |
| `EMG_IDENTITY_SERVICE_CLIENT_SECRET` (Sprint 3) | *(local-dev placeholder)* | Secret for the above — **never a real value outside `docker-compose.yml`** |
| `EMG_IDENTITY_SERVICE_TOKEN_AUDIENCE` (Sprint 3) | `emg-internal-services` | Expected `aud` claim on inbound service tokens |
| `EMG_IDENTITY_JWKS_CACHE_TTL_SECONDS` (Sprint 3) | `300` | `PyJWKClient` cache lifespan for JWKS lookups |
| `EMG_IDENTITY_FEDERATION_CONFIG_PATH` (Sprint 3) | `services/identity/config/federation.example.yaml` | Path to the federation configuration file |
| `EMG_IDENTITY_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` (Sprint 3) | `10` | `/auth/login` rate-limit budget |
| `EMG_IDENTITY_LOGIN_RATE_LIMIT_WINDOW_SECONDS` (Sprint 3) | `60.0` | `/auth/login` rate-limit window |

`keycloak_issuer` and `jwks_uri` (used for service-token validation) are
computed from `keycloak_base_url`/`keycloak_realm`, not independently
configurable — this keeps them from ever drifting out of sync.

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

# Sprint 3: machine-to-machine (Client Credentials) example
curl -X POST localhost:8080/realms/emg/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=emg-svc-authorization \
  -d client_secret=emg_svc_authorization_local_dev_secret_do_not_use_in_prod
```

## Testing

```bash
pytest services/identity/tests
```

Unit tests cover session issuance/verification/expiry/tampering
(`test_session.py`), the Keycloak client's success and failure paths
including the Client Credentials grant (`test_keycloak_client.py`), and the
HTTP surface end-to-end including failed-login audit-log emission and
rate-limiting (`test_auth_router.py`).

Sprint 3 additions: service-token validation against a locally-generated RSA
keypair — success, invalid audience, invalid issuer, expired, tampered,
missing scope, unrecognized client (`test_service_token_validator.py`);
structural human/machine token-separation tests
(`test_separation_human_vs_service.py`); federation configuration
validation, claim/group-role mapping, and safe missing-file handling
(`test_federation.py`); secret redaction (`test_redaction.py`); rate-limiter
unit tests (`test_rate_limit.py`); and HTTP-level tests for
`/auth/service-session` and `/federation/*`
(`test_service_auth_router.py`, `test_federation_router.py`). All of the
above run without Docker or a live Keycloak.

`test_integration_live_keycloak.py` is skipped by default and documents,
in its module docstring, the exact procedure for running it against a real
local Keycloak container (`docker compose up -d keycloak`, then
`EMG_IDENTITY_RUN_LIVE_KEYCLOAK_TESTS=1 pytest
services/identity/tests/test_integration_live_keycloak.py`).
