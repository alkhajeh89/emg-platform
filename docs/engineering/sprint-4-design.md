# Sprint 4 Design — EPIC-03 Authorization Platform

Scope: FEAT-03-1 (Policy Enforcement Point), FEAT-03-2 (ABAC Policy Engine
Integration), per `docs/architecture/EMG_Engineering_Backlog_v1.0.md` §6
(Sprint Planning, row 4) and US-03. FEAT-03-3 (RBAC Baseline Roles) and
FEAT-03-4 (Authorization Testing Harness) are Sprint 5 (§6, row 5) and are
not implemented here.

## US-03 traceability

> As a service developer, I want a reusable Policy Enforcement Point client,
> so that every module evaluates authorization consistently instead of
> reimplementing it.

Acceptance criteria and where each is met:

| Criterion | Where |
| --- | --- |
| PEP client is published as a shared library (FEAT-01-2) | `libs/python/emg-auth-client` (contract: `PolicyEnforcementPoint`, `Decision`, `AuthorizationRequest`) + new `libs/python/emg-policy-engine` (concrete ABAC evaluator + default PEP implementation) |
| A request with insufficient attributes is denied with an auditable reason | `PolicyEngine.evaluate()` returns `Decision(outcome="deny", reason=...)`; every deny is passed to `AuditEventSink.record_authorization_decision` |
| A request with sufficient attributes is allowed | `PolicyEngine.evaluate()` returns `Decision(outcome="allow", reason=...)` when a matching rule's conditions are satisfied |
| Denial and allow decisions are both logged (FEAT-04-1) | `AuditEventSink.record_authorization_decision` — interim `StructuredLogAuditSink` implementation via `emg_telemetry`, same documented stand-in pattern as Sprint 2's login/refresh logging, swappable for the real FEAT-04-1 pipeline with no call-site change |

## Decision: library-first, no live authorization service this sprint

US-03's acceptance criteria describe a **library contract**, not a network
API. `services/authz` (Module 5) stays `status: scaffolded` this sprint.
Authorization is evaluated **in-process**, inside the calling service, using
the caller's already-authenticated `Principal`/`ServicePrincipal` (Sprint
2/3 outputs) plus a local policy configuration — no new HTTP service, no new
network hop, no new port.

Rationale:

1. Matches the Backlog's literal acceptance criteria (a "PEP client," not a
   "PEP service").
2. Avoids a Zero Trust circularity the Master Plan §5 explicitly warns
   against in spirit ("no service-to-service call bypasses authenticated,
   policy-evaluated access") — if every service had to call a remote authz
   service to authorize a request, the authz service's own endpoint would
   itself need authorizing, recursively.
3. Matches the additive pattern used in Sprint 2 → Sprint 3: extend an
   existing Sprint-1-scaffolded contract (`emg-auth-client`) rather than
   introduce a new moving part before the Backlog asks for one.
4. `services/authz` remains available as the real target once a later
   sprint's acceptance criteria actually require a live PDP (Policy
   Decision Point) service — e.g. if a future module needs to authorize
   requests it did not itself authenticate. Nothing built this sprint
   blocks that.

## Decision: `ServicePrincipal` is referenced structurally, not imported

FEAT-03-1 must "support both `Principal` and `ServicePrincipal`" (Sprint 2
human identity, Sprint 3 machine identity). `ServicePrincipal` is defined in
`services/identity/src/emg_identity/service_principal.py` — a **service**,
not a **shared library** — so `libs/python/emg-auth-client` cannot import it
without inverting the dependency direction (libraries must not depend on
services).

`emg-auth-client` instead declares a `typing.Protocol` (`ServicePrincipalLike`)
describing the exact structural shape of Sprint 3's `ServicePrincipal`
(`client_id`, `service_name`, `roles`, `scopes`). Python's `Protocol` is
structural: `emg_identity.ServicePrincipal` satisfies it automatically,
verified by `mypy --strict` at every call site, with **zero changes to any
Sprint 3 file** — `service_principal.py` is untouched. This was a deliberate
alternative to relocating `ServicePrincipal` into the shared library, which
would have touched completed Sprint 3 code for no behavioral benefit.

## Decision: no changes to any existing Sprint 2/3 HTTP route

`get_current_principal` and `get_current_service_principal`
(`services/identity/src/emg_identity/dependencies.py`) are unchanged. A new,
additive `get_current_identity` dependency composes both (try human-session
verification first, fall back to service-token verification, fail closed if
neither succeeds) without modifying either. No existing route's behavior,
status codes, or response shape changes.

## Decision: one new, explicitly-labeled reference/demo endpoint

`GET /authz/check` is new. It is **not** new product functionality — it
exists solely to prove the PEP end-to-end (identity resolution → policy
evaluation → audit logging) against a real HTTP surface, the same role
`/auth/service-session` played for Sprint 3's `ServiceTokenValidator`. It
always returns HTTP 200 with the `Decision` in the body — this is an
introspection/reference endpoint ("what would the PEP decide"), not an
enforcement gate, so there is no ambiguity about repurposing HTTP status
codes for a demonstration surface. Real enforcement is the calling code's
responsibility (`if not decision.allowed: raise AuthorizationError(...)`),
demonstrated in tests, not forced onto an existing route.

## ABAC evaluation semantics (FEAT-03-2)

- **Default-deny, fail-closed.** No resource/action pair with zero matching
  policy rules is ever allowed. `PolicyConfig.default_effect` is fixed to
  `"deny"` — not a configurable field an operator could flip to `"allow"`.
- **Deny-overrides combining.** If both an `allow` rule and a `deny` rule
  match a request, `deny` wins. Standard fail-closed ABAC/XACML posture.
- **Human (`Principal`) conditions:** `required_roles` (any-of) AND
  `required_attributes` (every named attribute must hold one of the listed
  allowed values — e.g. `classification_clearance: [INTERNAL, CONFIDENTIAL,
  SECRET]`).
- **Machine (`ServicePrincipalLike`) conditions:** `required_roles` (any-of,
  matched against the service's registered roles) AND `required_scopes`
  (any-of, matched against the token's granted scopes) — `ServicePrincipal`
  has no `attributes`, by Sprint 3 design (machine identities carry no
  classification/department claims), so attribute conditions never apply to
  a machine caller and a rule that only specifies `required_attributes`
  cannot be satisfied by a service principal.
- Policy configuration is local, versioned, pydantic-validated, and loaded
  the same way `federation.example.yaml` is loaded in Sprint 3
  (`load_federation_config` pattern): safe default (empty ruleset →
  everything denied) on a missing file, hard validation error on a
  malformed one.

## Audit logging

`AuditEventSink` (Protocol, `services/identity/src/emg_identity/audit.py`)
gains `record_authorization_decision(*, subject, resource_type, action,
outcome, reason, correlation_id)`, additive to the Sprint 2/3 Protocol —
every existing method keeps its exact signature. `StructuredLogAuditSink`
implements it via the same `emg_telemetry` structured-logging path as every
other audit event this platform emits.

## Explicit exclusions (this sprint)

- FEAT-03-3 (RBAC Baseline Roles) — Sprint 5.
- FEAT-03-4 (Authorization Testing Harness, as a standalone automated
  framework) — Sprint 5. Sprint 4 still ships positive/negative tests for
  what it builds (US-03's own acceptance criteria require this), but does
  not build a general-purpose harness other modules plug into.
- `services/authz` going live as an HTTP service.
- FEAT-04-1 (real Audit Event Pipeline) — logging remains the same interim,
  documented `StructuredLogAuditSink` stand-in Sprint 2 established.
- Any Module 6–10 work.
- Sprint 5 is not started.
