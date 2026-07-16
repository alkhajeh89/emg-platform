# Identity Platform — Security Limitations & Deferred Items

Covers Sprint 2 (FEAT-02-1, FEAT-02-2), Sprint 3 (FEAT-02-3, FEAT-02-4),
Sprint 4 (FEAT-03-1, FEAT-03-2), and Sprint 5 (FEAT-03-3, FEAT-03-4). Each
item states what the current implementation does, what it does not do, and
when the gap is expected to close. Nothing here is silently accepted — every
limitation is a tracked, documented, deliberate scope boundary.

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

## Controls implemented (Sprint 4)

- **Default-deny, fail-closed authorization.** `emg_policy_engine.PolicyEngine.evaluate()`
  denies a request with no matching rule and a request whose matching
  rules' conditions are all unsatisfied — both are the same code path as an
  explicit deny, not a fallthrough. `PolicyConfig` has no "default effect"
  field that could flip this; an empty or missing policy file
  (`load_policy_config`) denies everything, never allows everything.
- **Deny-overrides combining algorithm.** When a request matches both an
  allow rule and a deny rule, the deny rule wins — verified both at the
  `PolicyEngine` unit level
  (`libs/python/emg-policy-engine/tests/test_engine.py`) and end-to-end over
  real HTTP (`services/identity/tests/test_authz_router.py`).
  `PolicyConfig`/loader validation additionally flags any rule with zero
  conditions (`required_roles`/`required_attributes`/`required_scopes` all
  empty) as a configuration problem, since such a rule matches every
  principal unconditionally (`validate_policy_config`).
- **Structural support for both identity kinds without an import
  inversion.** `emg_auth_client.ServicePrincipalLike` is a `typing.Protocol`
  matching `services/identity`'s `ServicePrincipal` field-for-field; the
  shared PEP contract accepts either a human `Principal` or a machine
  `ServicePrincipal` (`AuthorizedIdentity = Principal | ServicePrincipalLike`)
  without `libs/python/emg-auth-client` ever importing from a service.
- **Allow and deny decisions are both audit-logged.** `AuditEventSink.record_authorization_decision`
  (extending the same interim, structured-logging-backed sink Sprint 2/3
  use) is called for every `/authz/check` request regardless of outcome —
  US-03's "denial and allow decisions are both logged" acceptance
  criterion.
- **`/authz/check` is explicitly introspection, not enforcement.** It always
  returns HTTP 200 with the `Decision` in the body rather than mapping deny
  to an HTTP error — a deliberate design choice (see `routers/authz.py`'s
  module docstring) that keeps this reference endpoint from being mistaken
  for a real enforcement gate on any resource.

## Controls implemented (Sprint 5)

- **Governed RBAC baseline role vocabulary.** `emg_policy_engine.roles.ROLE_CATALOG`
  (FEAT-03-3) is the single authoritative list of the platform's roles, each
  with a category (human/service), description, and governing reference. It
  is a *vocabulary* the ABAC engine's `required_roles` conditions draw from —
  deliberately not a second authorization mechanism, permission matrix, or
  role hierarchy. It exposes no `evaluate`/decision method, and it does not
  alter `services/identity`'s `SERVICE_REGISTRY`.
- **Policy configuration references are validated against the catalog.**
  `validate_policy_config` flags any `PolicyRule.required_roles` value not
  present in `ROLE_CATALOG`, so a misspelled or unknown role is surfaced to
  operators (see the advisory-only limitation below for the scope of this
  control).
- **Reusable authorization testing harness.** `emg_policy_engine.testing`
  (FEAT-03-4: `AuthorizationScenario`, `assert_scenario`, `run_scenarios`)
  gives every service a shared, declarative way to assert positive and
  negative authorization outcomes, adopted in
  `services/identity/tests/test_authz_scenarios.py`. No pytest runtime
  dependency and no YAML DSL, keeping the package's dependency and
  complexity footprint unchanged.

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
- **No live, network-reachable authorization service** (Sprint 4 —
  deliberate library-first design choice, not a gap to close this sprint).
  `services/authz` remains scaffolded (`service.yaml` only); the PEP and
  ABAC engine are in-process libraries, consumed directly by whichever
  service embeds them.
- **Nothing in this codebase actually enforces a `/authz/check` decision
  yet** (Sprint 4). No Sprint 2/3 route in `services/identity` (or anywhere
  else) calls the PEP and rejects a request based on its `Decision` — that
  is each future adopting service's own responsibility, and has not been
  done anywhere as of Sprint 4.
- **`policy.example.yaml` is illustrative, local-development-only
  configuration** (Sprint 4), same status as `federation.example.yaml`. A
  real deployment authors its own policy file.
- **Unknown-role validation is advisory, not enforcing** (Sprint 5,
  FEAT-03-3). `validate_policy_config` *reports* a `required_roles` value not
  present in `ROLE_CATALOG`, but `load_policy_config` still loads the policy
  successfully — a typo'd role name is a warning, not a load-time rejection.
  Callers that want fail-closed behavior must inspect
  `validate_policy_config`'s output and act on it themselves. Hardening this
  into a load-blocking failure is a candidate for a future sprint once role
  governance is fully owned by the Policy Platform Team (ADR-016 §1). Note
  the ABAC engine remains fail-closed regardless: an unknown role in a rule
  simply never matches a real principal, so it cannot grant access — the
  advisory gap is about catching operator mistakes early, not about a
  privilege-escalation path.
- **The RBAC catalog is a vocabulary, not an enforcement layer** (Sprint 5,
  FEAT-03-3 — deliberate design boundary, not a gap). It does not define
  role→permission mappings, role hierarchy, or inheritance; all authorization
  decisions are made solely by the ABAC `PolicyEngine`.
- **No live authorization service, and no FEAT-04-1 audit pipeline yet**
  (Sprint 5). `services/authz` remains scaffolded (unchanged from Sprint 4),
  and FEAT-04-1 (the real append-only Audit Event Pipeline) was rescheduled
  out of Sprint 5 to the next Audit sprint — allow/deny decisions still log
  through the interim `StructuredLogAuditSink` established in Sprint 4.

## Deferred to later sprints (not started)

- Module 5 Authorization Platform: a live network-reachable authorization
  service, if a future sprint's design calls for one (EPIC-03 is otherwise
  complete after Sprint 5's FEAT-03-3/03-4). Hardening the advisory
  unknown-role check into a load-blocking failure is also deferred.
- Module 6 Audit Event Pipeline / append-only audit store (EPIC-04),
  **including FEAT-04-1**, which was grouped with FEAT-03-3/03-4 in the
  Backlog's Sprint 5 row but rescheduled to the next Audit implementation
  sprint (engineering sequencing only — see `sprint-5-design.md` and
  `ARCHITECTURE_STATUS.md`).
- Knowledge Graph, Search, GraphRAG, AI agents, Decision Intelligence
  (EPIC-05 onward).
- Frontend features (EPIC-10 onward).
