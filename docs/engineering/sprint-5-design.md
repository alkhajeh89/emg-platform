# Sprint 5 Design — EPIC-03 Authorization Completion

Scope: FEAT-03-3 (RBAC Baseline Roles), FEAT-03-4 (Authorization Testing
Harness), per `docs/architecture/EMG_Engineering_Backlog_v1.0.md` §6 (Sprint
Planning, row 5) and the completion of EPIC-03's authorization baseline begun
in Sprint 4 (FEAT-03-1 Policy Enforcement Point, FEAT-03-2 ABAC Policy Engine
Integration).

## Scope decision: FEAT-04-1 rescheduled out of Sprint 5

The Backlog's Sprint 5 row (§6) groups three features:

| Feature | Epic | Status in Sprint 5 |
| --- | --- | --- |
| FEAT-03-3 RBAC Baseline Roles | EPIC-03 | Implemented this sprint |
| FEAT-03-4 Authorization Testing Harness | EPIC-03 | Implemented this sprint |
| FEAT-04-1 Audit Event Pipeline | EPIC-04 | **Rescheduled to the next Audit sprint** |

Sprint 5 completes EPIC-03 (authorization) only. FEAT-04-1 begins EPIC-04
(audit) — a different epic, a different module (Module 6), and a different
accountable owner grouping. Sequencing the two EPIC-03 features together as a
clean "authorization completion" sprint, and starting EPIC-04 as its own
focused unit, keeps each sprint single-epic and keeps the audit pipeline from
being a rushed tail-end of an authorization sprint.

This is an **engineering-sequencing decision only**. It:

- does **not** modify the frozen Architecture Baseline v1.0;
- does **not** redesign Module 6 (Enterprise Audit, Provenance & Digital
  Evidence Platform), which remains architecture-approved and frozen;
- does **not** create, require, or imply a new ADR;
- does **not** change the Backlog's feature-to-epic assignments — FEAT-04-1
  is still an EPIC-04 feature; only the sprint in which it is *built* has
  moved.

It is recorded transparently in `ARCHITECTURE_STATUS.md`,
`EMG_PRODUCT_VISION.md`, `CHANGELOG.md`, and the Sprint 5 status report.
FEAT-04-1 is not implemented, partially implemented, or stubbed during Sprint
5.

## FEAT-03-3 — RBAC Baseline Roles

### Decision: the role catalog is a governed vocabulary, not an enforcement mechanism

Module 5 is architecturally ABAC-based. Sprint 4 built `PolicyEngine` around
attribute/role/scope *conditions* (`required_roles`, `required_attributes`,
`required_scopes`) — there is exactly one authorization mechanism in this
platform, and it evaluates attributes.

"RBAC Baseline Roles — Foundational role catalog" (Backlog §3) is therefore
implemented as the **authoritative vocabulary that ABAC rules draw their
`required_roles` values from**, not as a competing role→permission
authorization path. Concretely, the catalog:

- enumerates every platform role, with a category (human vs. service), a
  description, and a governing-architecture reference;
- has **no** `evaluate()`, decision, or enforcement method of any kind;
- is consumed only as a validation reference (does a policy rule name a role
  that actually exists?) and as documentation.

There is deliberately **no permission matrix** (role → allowed
actions/resources) and **no role hierarchy or inheritance**. Keycloak
composite roles are not used anywhere in this repository, and ABAC rules
already express what a role may do via `required_roles` on each rule —
introducing a second, role-centric permission model would create exactly the
"two competing authorization systems" outcome this decision exists to
prevent.

### Roles

Only roles already proven to exist in the repository and the Keycloak realm
seed (`tools/seed-data/keycloak/emg-realm.json`) are catalogued. No new role
is invented.

| Role | Category | Origin |
| --- | --- | --- |
| `platform-user` | human | Realm seed (Sprint 2) — baseline authenticated user |
| `investigator` | human | Realm seed (Sprint 2) — case investigator |
| `decision-maker` | human | Realm seed (Sprint 2) — accountable decision-maker |
| `knowledge-steward` | human | Realm seed (Sprint 2) — Knowledge Graph steward |
| `service-account` | service | Realm seed (Sprint 3, FEAT-02-3) — baseline machine role |
| `svc-identity` | service | Realm seed (Sprint 3) — Identity Service principal |
| `svc-authorization` | service | Realm seed (Sprint 3) — Authorization Service principal |
| `svc-audit` | service | Realm seed (Sprint 3) — Audit Service principal |

### Placement

The catalog lives in `libs/python/emg-policy-engine` — Module 5's concrete
implementation package, next to the `PolicyEngine` that consumes the
vocabulary. It does **not** go in `emg-auth-client` (identity contracts), and
it does **not** touch `services/identity`'s `SERVICE_REGISTRY`
(`service_registry.py`), which is service-*identity* registration — a
distinct concern from the role *vocabulary*. `SERVICE_REGISTRY` behavior is
unchanged this sprint.

### Advisory unknown-role validation

`validate_policy_config` (in `loader.py`) gains one additive check: any
`PolicyRule.required_roles` value not present in `ROLE_CATALOG` is appended to
the returned problem list. This is **advisory**, consistent with every other
check that function already performs (duplicate rule ids, condition-free
rules, empty attribute allow-lists): it produces an explicit validation
problem but does **not** raise or block loading. The only hard failure mode
for policy configuration remains a malformed file (pydantic `ValidationError`
from `load_policy_config`), unchanged from Sprint 4.

This advisory-only posture is a **known limitation**, documented in
`docs/engineering/security-limitations.md`: a typo'd role in a policy file is
surfaced as a warning by `validate_policy_config`, not rejected at load time.
A future sprint may harden this into a load-time failure once role governance
is fully owned by the Policy Platform Team (ADR-016 §1).

Every role currently referenced in `services/identity/config/policy.example.yaml`
(`platform-user`, `knowledge-steward`, `svc-identity`, `svc-authorization`,
`svc-audit`) already appears in `ROLE_CATALOG`, so this check passes clean
against the shipped example configuration — no existing config is changed.

## FEAT-03-4 — Authorization Testing Harness

### Decision: a small reusable toolkit, not a test framework

Sprint 4 already ships hand-written positive/negative authorization tests
(`test_engine.py`, `test_authz_router.py`). FEAT-03-4 is not "more of those";
it is a **reusable, declarative scenario/assertion toolkit** so that any
future service adopting the PEP can express authorization expectations
declaratively rather than re-hand-rolling HTTP/engine test boilerplate.

The harness is deliberately three small pieces:

- `AuthorizationScenario` — a frozen dataclass: `name`, `principal`
  (`AuthorizedIdentity`), `resource_type`, `action`, `expected_outcome`
  (`DecisionOutcome`), optional `expected_policy_id`.
- `assert_scenario(pep, scenario)` — evaluates the scenario against any
  `PolicyEnforcementPoint` and raises a plain `AssertionError` (with a
  message naming principal/resource/action and expected-vs-actual) on
  mismatch.
- `run_scenarios(pep, scenarios)` — batch runner returning a list of failure
  messages (empty list = all passed), for a single "harness green" check.

Deliberate constraints (per approved scope):

- **No pytest runtime dependency.** The harness uses a plain `assert` /
  returns strings; it works under pytest and standalone. pytest remains a
  dev-only dependency, unchanged.
- **No YAML DSL / no config-file-driven scenarios.** Scenarios are plain
  Python objects.
- **No unnecessary framework complexity.** No plugin system, no runner
  discovery, no new abstraction layer. If this proves too thin once more
  consumers exist, expanding it is a future sprint's decision — not something
  to over-build now.

### Placement and proof of adoption

The harness lives in `libs/python/emg-policy-engine/src/emg_policy_engine/testing.py`,
so any service already depending on `emg-policy-engine` gets it with no new
dependency.

Real adoption is proven by `services/identity/tests/test_authz_scenarios.py`
— an **additive** suite expressing a representative slice of
`policy.example.yaml`'s scenarios via the harness. It is intentionally *not*
a rewrite of Sprint 4's `test_authz_router.py` (that Sprint-4-signed-off file
is left untouched); both suites coexist and both pass.

## Audit logging

No change. Sprint 4's `AuditEventSink.record_authorization_decision` (interim
`StructuredLogAuditSink`) is unchanged; FEAT-04-1 (the real Audit Event
Pipeline that would replace it) is explicitly out of scope (see the scope
decision above).

## Explicit exclusions (this sprint)

- FEAT-04-1 (Audit Event Pipeline) — rescheduled to the next Audit sprint.
- A permission matrix, role hierarchy, or role inheritance for FEAT-03-3.
- Any new role beyond the eight already proven to exist.
- Any change to `SERVICE_REGISTRY` behavior (`services/identity`).
- Hard (load-blocking) unknown-role enforcement — advisory only this sprint.
- `services/authz` going live as an HTTP service (unchanged from Sprint 4).
- Any Module 6–10 work.
- Sprint 6 is not started.
