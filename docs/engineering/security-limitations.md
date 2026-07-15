# Identity Platform — Security Limitations & Deferred Items

Covers Sprint 2 (FEAT-02-1, FEAT-02-2) and Sprint 3 (FEAT-02-3, FEAT-02-4).
Each item states what the current implementation does, what it does not do,
and when the gap is expected to close. Nothing here is silently accepted —
every limitation is a tracked, documented, deliberate scope boundary.

## Controls implemented (Sprint 3)

- **No client secret in source control.** Every secret value committed to
  `tools/seed-data/keycloak/emg-realm.json` or `config.py`'s defaults is a
  clearly-labeled, non-production placeholder (`..._local_dev_secret_do_not_use_in_prod`
  suffix), used only by `docker-compose.yml`. Real environments source every
  secret from the centralized secrets store (Engineering Master Plan §5).
- **Secret redaction in logs.** Primary control is structural — no method on
  `AuditEventSink` (`audit.py`) accepts a raw secret or token as a
  parameter, so there is no call path that logs one. `redact.py` is the
  documented backstop for free-text values that might incidentally contain
  a secret-shaped string (e.g. an upstream error body), applied to the
  `/federation/providers` response's `connection_settings` and available for
  any future free-text logging.
- **Fail-closed token validation.** Both `SessionManager.verify` (HS256,
  human) and `ServiceTokenValidator.validate` (RS256, machine) raise
  `AuthorizationError` on every failure path — invalid signature, wrong
  issuer, wrong audience, expired, not-yet-valid, or (service tokens only)
  unrecognized client / missing required scope. There is no code path in
  either that returns a partially-trusted principal.
- **Separation between human and machine identities.** Enforced
  cryptographically, not by a flag: human EMG session tokens are HS256,
  service tokens are Keycloak-issued RS256 via JWKS — a human token
  presented to `ServiceTokenValidator` (or vice versa) fails signature
  verification before any claim is inspected. Enforced again structurally:
  `Principal` and `ServicePrincipal` are distinct dataclasses, and
  `get_current_principal` / `get_current_service_principal` are separate
  FastAPI dependencies, so a route cannot accidentally accept either
  identity kind interchangeably. See
  `services/identity/tests/test_separation_human_vs_service.py`.
- **Correlation identifiers for auth events.** Every `AuditEventSink` call
  site (both Sprint 2 human-auth events and Sprint 3 service-auth events)
  threads the request's `correlation_id` (ADR-015, `emg_telemetry`) through.
- **Structured allow/deny authentication telemetry.** `StructuredLogAuditSink`
  emits the ADR-015 actor/module/action/outcome shape for every login
  success/failure, refresh failure, and (Sprint 3) service-auth
  success/failure.
- **Rate-limiting readiness for token requests.** `InMemoryRateLimiter`
  (`rate_limit.py`) guards `/auth/login`, configurable via
  `EMG_IDENTITY_LOGIN_RATE_LIMIT_MAX_ATTEMPTS` /
  `EMG_IDENTITY_LOGIN_RATE_LIMIT_WINDOW_SECONDS`.
- **Rotation-ready client-secret configuration.** Every client secret
  (`keycloak_client_secret`, `service_client_secret`, and every Keycloak
  client's `secret` in the realm seed) is sourced from environment
  variables / `Settings`, never hardcoded into logic — rotating a secret is
  an environment-variable/secrets-store change, not a code change.

## Known limitations (tracked, carried from Sprint 2 unless noted)

- **No session revocation** (Sprint 2). A compromised EMG refresh token
  cannot be actively revoked before its natural expiry (12h default) because
  there is no persistent session store yet. Revisit when Module 6 (audit /
  session storage, EPIC-04) lands.
- **`StructuredLogAuditSink` is not the real audit pipeline** (Sprint 2,
  extended Sprint 3 with service-auth events). It emits the same shape
  Module 6's append-only store will expect, so the swap is a one-line
  dependency change, not a rewrite — but until FEAT-04-1 ships, authentication
  and service-authentication events are durable only as long as log
  retention allows, not append-only-store-guaranteed.
- **`InMemoryRateLimiter` is readiness, not a production control** (Sprint
  3). Single-process, in-memory, resets on restart — unsuitable for a
  horizontally-scaled deployment (Engineering Master Plan §5, ADR-017 §2).
  The `RateLimiter` Protocol is the swap-in seam for a Redis- or
  gateway-backed limiter; no caller (`routers/auth.py`) needs to change when
  that swap happens.
- **The identity service does not issue or broker M2M tokens for other
  services** (Sprint 3, deliberate design choice, not a gap to close). See
  `routers/service_auth.py`'s module docstring. Each service is expected to
  hold and use its own Keycloak client credentials directly.
- **Federation is configuration-and-validation readiness only** (Sprint 3).
  No LDAP, Active Directory, external OIDC, or SAML client code is invoked
  by this service; actual protocol handling is Keycloak's own User
  Federation / Identity Brokering, configured per deployment. See
  `docs/engineering/federation-readiness.md`.
- **`redact_text`'s pattern matching is best-effort, not a guarantee**
  (Sprint 3). It catches common `"secret": "..."` / `key=value` shapes in
  free text; it is documented as a backstop specifically because call sites
  are expected to avoid logging raw upstream response bodies in the first
  place (`keycloak_client.py` never does).
- **No production LDAP/Active Directory connection, and no connection to a
  real government or production identity provider** (Sprint 3 — explicit
  scope exclusion, not a gap). `federation.example.yaml` contains
  placeholder values only.

## Deferred to later sprints (not started)

- Module 5 Authorization Platform: ABAC Policy Engine, full RBAC
  management, user administration portal, organization/tenant management
  (EPIC-03).
- Module 6 Audit Event Pipeline / append-only audit store (EPIC-04).
- Knowledge Graph, Search, GraphRAG, AI agents, Decision Intelligence
  (EPIC-05 onward).
- Frontend features (EPIC-10 onward).
