# emg-policy-engine

Local ABAC (Attribute-Based Access Control) policy evaluation engine and the
default `PolicyEnforcementPoint` implementation — Module 5 (Enterprise
Authorization & Policy Platform), FEAT-03-2. Added Sprint 4.

Part of the EMG™ shared libraries workspace (Module 3, ADR-012), same tier
as `emg-auth-client` (which owns the `PolicyEnforcementPoint`/`Decision`
*contract* this package implements — see
`docs/engineering/sprint-4-design.md` for the contract/implementation
split rationale).

## What this is

- `PolicyRule` / `PolicyConfig` — pydantic schema for a versioned, local ABAC
  ruleset (role and attribute/scope conditions per resource type + action).
- `load_policy_config()` / `load_validated_policy_config()` /
  `default_policy_config()` / `validate_policy_config()`
  — safe-default config loading, same pattern as Sprint 3's
  `emg_identity.federation` module: a missing file is not an error (falls
  back to an empty, default-deny ruleset); a malformed *existing* file is.
- `PolicyEngine.evaluate()` — pure, local, default-deny, deny-overrides ABAC
  evaluation against a `Principal` or a structurally-`ServicePrincipalLike`
  identity (`emg_auth_client.AuthorizedIdentity`). No network calls, no
  database.
- `LocalPolicyEnforcementPoint` — the default `PolicyEnforcementPoint`
  (`emg_auth_client.pep`) implementation, wrapping `PolicyEngine` behind the
  shared contract every service programs against.

## Sprint 5 additions (FEAT-03-3, FEAT-03-4)

- `roles.py` — the **RBAC baseline role catalog** (FEAT-03-3):
  `ROLE_CATALOG`, a governed, versioned dict of `RoleDefinition`s for the
  eight roles that already exist in the repository and the Keycloak realm
  seed (`platform-user`, `investigator`, `decision-maker`,
  `knowledge-steward`; `service-account`, `svc-identity`,
  `svc-authorization`, `svc-audit`). This is a role **vocabulary** the ABAC
  engine's `required_roles` conditions draw from — **not** a second
  authorization mechanism. No permission matrix, no role hierarchy, no
  enforcement method. `validate_policy_config` reports an unknown role and
  production composition uses `load_validated_policy_config` to reject every
  reported semantic problem before serving traffic. See
  `docs/engineering/sprint-5-design.md`.
- `testing.py` — the **authorization testing harness** (FEAT-03-4):
  `AuthorizationScenario` (a declarative expectation), `assert_scenario`
  (raises `AssertionError` on mismatch), and `run_scenarios` (batch runner
  returning failure messages). No pytest runtime dependency, no YAML DSL.
  Real adoption is demonstrated in
  `services/identity/tests/test_authz_scenarios.py`.

## What this is not

- Not a network service. There is no HTTP server in this package and no
  client for one. `services/authz` (Module 5's eventual dedicated service)
  remains scaffolded — see `docs/engineering/sprint-4-design.md`,
  "Decision: library-first, no live authorization service this sprint."
- Not a second authorization or enforcement mechanism. `ROLE_CATALOG` is a
  vocabulary, not a role→permission engine; all authorization decisions are
  made by `PolicyEngine` (ABAC) and nothing else.
- Not FEAT-04-1 (Audit Event Pipeline). That EPIC-04 feature — grouped with
  FEAT-03-3/03-4 in the Backlog's Sprint 5 row — was rescheduled to the next
  Audit implementation sprint (engineering sequencing only; see
  `docs/engineering/sprint-5-design.md`). Allow/deny decisions still log
  through the interim `AuditEventSink` established in Sprint 4.
