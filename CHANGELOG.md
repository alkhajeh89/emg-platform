# Changelog

All notable changes to the EMG™ Core Platform monorepo are documented here,
generated from Conventional Commits (`CONTRIBUTING.md`).

## [Unreleased]

### Sprint 4 — EPIC-03 Authorization Platform (FEAT-03-1, FEAT-03-2)

- `libs/python/emg-auth-client` (0.2.0): the Policy Enforcement Point
  contract — `Decision`, `AuthorizationRequest`, `PolicyEnforcementPoint`
  (a `typing.Protocol`), and `ServicePrincipalLike` (a structural Protocol
  matching `services/identity`'s `ServicePrincipal` field-for-field, so a
  shared library can type "either identity kind" without importing from a
  service).
- New package `libs/python/emg-policy-engine` (0.1.0): `PolicyEngine` (ABAC
  evaluation — default-deny, fail-closed, deny-overrides combining),
  `PolicyConfig`/`PolicyRule` (pydantic schema, no configurable "default
  effect"), `load_policy_config`/`default_policy_config`/`validate_policy_config`
  (same safe-default-on-missing-file, hard-error-on-malformed-file pattern
  as Sprint 3's `federation.py`), and `LocalPolicyEnforcementPoint`.
- `services/identity` (0.4.0): reference integration only — `GET
  /authz/check` (always HTTP 200, `Decision` in the body; introspection,
  not enforcement), `policy_enforcement_point_dependency` (loads
  `config/policy.example.yaml`), `get_current_identity` (accepts either a
  human `Principal` or a machine `ServicePrincipal`, used only by this new
  endpoint), and `AuditEventSink.record_authorization_decision` (both allow
  and deny decisions are logged — US-03). No existing Sprint 2/3 route,
  dependency, or behavior changed.
- `services/identity/config/policy.example.yaml`: illustrative local-dev
  ABAC rules exercising an allow rule, a deny rule that overrides it for a
  specific role (deny-overrides), and a service-scope-based allow rule.
- Explicitly not implemented this sprint (approved scope boundary):
  FEAT-03-3 (RBAC Baseline Roles), FEAT-03-4 (Authorization Testing Harness),
  and any live, network-reachable `services/authz` HTTP service —
  `services/authz` remains scaffolded.
- Governance file corrections (`CLAUDE_WORKFLOW.md`, `ARCHITECTURE_STATUS.md`,
  `EMG_PRODUCT_VISION.md`): converted from RTF-content-in-a-`.md`-file to
  genuine plain UTF-8 Markdown, and `ARCHITECTURE_STATUS.md`/
  `EMG_PRODUCT_VISION.md` corrected to match the actual repository state
  (architecture-approved vs. engineering-complete status per module, only
  ADR-014–017 present, roadmap deferring to the Engineering Backlog instead
  of restating it).
- New docs: `docs/engineering/sprint-4-design.md`; extended
  `docs/engineering/security-limitations.md` with Sprint 4 controls and
  limitations.
- New tests: `libs/python/emg-auth-client/tests/test_import.py` extended
  for the new PEP types; `libs/python/emg-policy-engine/tests/test_import.py`,
  `test_engine.py` (9 cases covering the full ABAC combining/condition
  semantics), `test_loader.py`; `services/identity/tests/test_authz_router.py`
  (HTTP-level, loads the real `policy.example.yaml`, covers both identity
  kinds, deny-overrides, default-deny, and audit logging).

### Sprint 3 — EPIC-02 Identity (FEAT-02-3, FEAT-02-4)

- `services/identity`: OAuth 2.0 Client Credentials (M2M) authentication —
  `KeycloakClient.client_credentials_token()` for outbound service calls,
  `ServiceTokenValidator` for inbound validation (RS256/JWKS signature,
  issuer, audience, expiry, registered-client, optional scope) of other
  services' tokens (FEAT-02-3).
- `services/identity`: representative service identities registered for the
  Identity, Authorization, and Audit services (`service_registry.py`,
  `tools/seed-data/keycloak/emg-realm.json`) — registration only, no
  downstream service business logic implemented.
- `services/identity`: structural separation between human sessions and
  service identities — `ServicePrincipal` is a distinct type from
  `Principal`; service tokens (RS256/JWKS) and human session tokens (HS256)
  are cryptographically unrelated trust paths, so one cannot be presented
  where the other is required.
- `services/identity`: identity federation readiness (`federation.py`) — a
  provider-agnostic configuration schema and validator for LDAP/Active
  Directory/external OIDC/SAML readiness, claim and group-to-role mapping
  projection, and air-gapped-safe defaults. No external directory is
  connected (FEAT-02-4).
- New endpoints: `GET /auth/service-session` (service-token "whoami"),
  `GET /federation/providers` (redacted listing), `GET /federation/health`
  (configuration validation status).
- `services/identity`: rate-limiting readiness for `/auth/login`
  (`rate_limit.py`, `InMemoryRateLimiter`) and a secret-redaction utility
  (`redact.py`) applied to the `/federation/providers` response.
- `tools/seed-data/keycloak/emg-realm.json`: three new service-account-only
  confidential clients, their least-privilege realm roles, and a client
  scope adding the `emg-internal-services` audience to service-account
  tokens.
- New docs: `docs/engineering/service-identity-registration.md`,
  `docs/engineering/federation-readiness.md`,
  `docs/engineering/security-limitations.md`.
- New tests: `test_service_token_validator.py`,
  `test_separation_human_vs_service.py`, `test_federation.py`,
  `test_redaction.py`, `test_rate_limit.py`, `test_service_auth_router.py`,
  `test_federation_router.py`, plus Client Credentials coverage added to
  `test_keycloak_client.py` and a login-rate-limit 429 test added to
  `test_auth_router.py`. `test_integration_live_keycloak.py` is an
  opt-in, skipped-by-default suite documenting the live-Keycloak procedure.
- **Fix (test flakiness, `services/identity/tests/test_session.py`):**
  `test_verify_rejects_tampered_signature` corrupted only the final
  base64url character of a JWT signature, which carries "don't-care"
  padding bits and roughly 1-in-4 decodes to identical bytes — an existing
  Sprint 2 test with a latent ~25% flake rate, discovered while extending
  the tampering test pattern for Sprint 3's `ServiceTokenValidator`. Fixed
  to corrupt a middle character instead (deterministic). See
  `SPRINT-3-STATUS.md`.

### Sprint 2 — EPIC-02 Identity (FEAT-02-1, FEAT-02-2)

- `services/identity`: Keycloak-backed authentication (Direct Access Grants)
  against the local-dev realm seeded in
  `tools/seed-data/keycloak/emg-realm.json` (FEAT-02-1).
- `services/identity`: EMG-minted session issuance, refresh (with rotation),
  and expiry, independent of Keycloak's own token lifetimes; session claims
  carry `roles`/`attributes` matching `emg_auth_client.Principal` for
  Module 5's future PEP (FEAT-02-2).
- `SessionAuthClient`: concrete `emg_auth_client.AuthClient` implementation
  (Sprint 1 shipped the Protocol only).
- Interim authentication-event logging (`StructuredLogAuditSink`) standing
  in for the audit pipeline until FEAT-04-1 (Sprint 5-6).
- Wired `identity` into `docker-compose.yml` and a per-service CI workflow
  (`.github/workflows/service-identity.yml`) using the Sprint 1 reusable
  pipeline template.
- **Fix (libs/python/emg-telemetry):** `get_logger()`'s `extra=` handling
  crashed with `KeyError: Attempt to overwrite 'module' in LogRecord`
  whenever a caller passed the ADR-015 schema field `module` — a reserved
  `logging.LogRecord` attribute name. Discovered while wiring Sprint 2's
  audit logging (US-02's "failed authentication is logged" acceptance
  criterion depends on this). Fixed by namespacing the internal attribute
  names; the public `extra=` schema (`actor`, `module`, `action`, `outcome`)
  is unchanged. See `SPRINT-2-STATUS.md` for details.

### Sprint 1 — EPIC-01 Foundation (FEAT-01-1 through FEAT-01-4)

- Repository bootstrap: monorepo structure, branch protection, CODEOWNERS
  derived from ADR-016 (FEAT-01-1).
- Shared libraries scaffolding: common types, error handling, telemetry
  client, auth client interfaces, API client conventions (FEAT-01-2).
- Local development environment: containerized orchestration, seed data
  fixture scaffolding (FEAT-01-3).
- CI pipeline skeleton: staged pipeline template all services inherit
  (FEAT-01-4).
