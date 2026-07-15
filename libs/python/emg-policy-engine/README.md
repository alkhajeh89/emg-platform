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
- `load_policy_config()` / `default_policy_config()` / `validate_policy_config()`
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

## What this is not

- Not a network service. There is no HTTP server in this package and no
  client for one. `services/authz` (Module 5's eventual dedicated service)
  remains scaffolded this sprint — see `docs/engineering/sprint-4-design.md`,
  "Decision: library-first, no live authorization service this sprint."
- Not FEAT-03-3 (RBAC Baseline Roles) or FEAT-03-4 (Authorization Testing
  Harness) — both Sprint 5.
