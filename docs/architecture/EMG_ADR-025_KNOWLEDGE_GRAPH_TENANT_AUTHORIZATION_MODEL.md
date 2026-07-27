# ADR-025 — Knowledge Graph Tenant & Authorization Model

## 1. Title

Knowledge Graph Tenant & Authorization Model — Operation-Level RBAC/ABAC Enforcement
for the Knowledge Graph Query API (Knowledge Graph Integration Closure, Group C
design input)

## 2. Status

**Accepted and implemented (Group C, 2026-07-27).** Originally proposed as a
design-only architecture decision; approved, and Group C (Knowledge Graph
Authorization Enforcement) implemented it in full the same day. See §18
"Implementation Notes" for two small, evidence-driven adjustments discovered
during implementation (neither changes any decision in §8).

**Date:** 2026-07-27
**Deciders:** Principal Security Architect / Architecture Board (EMG Platform), CISO
(Accountable Owner, Module 5 — ADR-016 §1, item 2)
**Supersedes:** none
**Related:** ADR-016 (Enterprise Ownership Registry), ADR-020 (Knowledge Ingestion),
ADR-021 (Enterprise API Strategy), ADR-022/023/024 (Knowledge Graph Revision Build /
History / Query Engine), `EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9–§12, §16, §17, §22,
`EMG_ARCHITECTURE_DECISION_REGISTER.md` (OBS-A-002), Knowledge Graph Integration
Closure implementation specification (Groups C–F)
**Explicitly does not supersede or reopen:** ADR-022, ADR-023, ADR-024 (Query Engine
contracts, revision model, pagination/temporal semantics — all treated as repository
fact, unchanged)

## 3. Context

The Knowledge Graph Query API (Sprint 7.4, ADR-024) is live and read-only. It already
authenticates every inbound request and resolves a tenant (`services/knowledge-graph/
src/emg_knowledge_graph_api/authn.py`), and every query it executes is scoped to that
tenant (`GraphQueryScope.tenant`, threaded into every `GraphStore`/`GraphRevisionReader`
call). What it does **not** do today is ask "is this authenticated caller *permitted*
to perform this operation" — any caller holding a valid service token for tenant `T`
can call every route for tenant `T`'s data. There is no role, scope, or classification
gate anywhere in the HTTP or application layer.

Separately, the platform already has a real, tested, in-process ABAC evaluator
(`emg-policy-engine`) and a Policy Enforcement Point contract (`emg-auth-client`), both
delivered in Sprint 4 (FEAT-03-1/03-2) and adopted so far by exactly one service
(`services/identity`, via a demonstration/introspection endpoint, `GET /authz/check`,
that is explicitly documented as *not* an enforcement gate). No service in this
repository enforces an authorization decision on its own routes today — the identity
README states this outright: *"Each service that adopts the PEP is responsible for its
own `if not decision.allowed: raise AuthorizationError(...)` at its own call sites —
not yet done anywhere in this codebase."*

This ADR closes that gap for exactly one service — the Knowledge Graph Query API — by
deciding how an authorization decision is obtained, where it is enforced, what
information it consumes, and how it fails, without changing ADR-024's Query Engine
contracts, without inventing a second authorization mechanism next to
`emg-policy-engine`, and without doing any of the several adjacent things a reader
might expect an "authorization ADR" to also cover (classification enforcement,
mutation API, audit reconciliation — see §16, Non-Goals).

## 4. Problem Statement

Decide, for the existing seven read routes in `emg_knowledge_graph_api/routers/
knowledge_graph.py` (`get_entity`, `list_entities`, `get_edge`, `list_edges`,
`list_neighbors`, `find_shortest_path`, `get_entity_history`):

1. What is protected (security boundary) and what, specifically, is being decided
   about each request (authorization boundary)?
2. At which architectural layer is the decision made and enforced?
3. What inputs does that decision require, restricted to what the repository already
   models?
4. Which operations are in scope?
5. What does the caller see on a denial, and why?
6. How does this reuse `emg-policy-engine`/`emg-auth-client` instead of introducing a
   second framework?
7. In what order do tenant resolution and authorization happen?
8. What is deliberately left as a reserved extension point for later ADRs (ADR-026
   classification enforcement, ADR-027 mutation API) rather than decided now?

## 5. Existing Architecture (repository evidence)

Established by direct inspection of the current working tree; restated here as
decision input, not re-derived.

**Authentication / tenant resolution (unchanged by this ADR):**

- `emg_knowledge_graph_api/authn.py` — `TenantServiceTokenValidator` verifies an RS256
  Bearer service token against the realm JWKS (issuer/audience/expiry checked),
  extracts `client_id`/`roles`/`scopes` into a `ServicePrincipal`, and requires a
  resolvable `tenant_claim` (default `"tenant_id"`), producing a `CallerContext
  (principal, tenant)`. A request can never supply or override its own tenant — the
  tenant is only ever read from the verified token. Any failure raises
  `emg_errors.AuthorizationError`, mapped to HTTP 401
  (`emg_knowledge_graph_api/errors.py`).
- This module's own docstring states it is *"the first tenant-context mechanism in the
  platform, not a reuse of an established one"* — no other service (`audit`, `identity`)
  extracts a tenant claim from a token today.
- Only machine `ServicePrincipal` callers exist in this service's authn path today; no
  human `Principal` (session-token) path has been built for the Knowledge Graph API.

**Tenant scoping in the query path (unchanged by this ADR):**

- Every route builds `GraphQueryScope(tenant=caller.tenant, revision_number=...)` and
  passes it into the one matching `KnowledgeGraphApplication` method
  (`services/knowledge-graph/src/emg_knowledge_graph_api/routers/knowledge_graph.py`).
  `GraphQueryScope.validate()` (`emg_knowledge_graph/commands.py`) rejects a non-`TenantId`
  value outright.
- `GraphStore`/`GraphTransaction` (`emg_platform_core/ports/graph_store.py`) require a
  `TenantId` on every `read`/`write`/`transaction` call — tenant scoping is a
  type-level, structural guarantee, not a policy-rule-driven one.
- `emg_knowledge_graph`'s own dependency-boundary test forbids importing
  `emg_persistence`/adapter internals and forbids declaring domain-shaped classes —
  this layer has **no** principal/role/scope parameter anywhere in its contracts
  (`commands.py`, `service.py`), and this ADR does not add one.

**Authorization primitives that already exist, unused by any live enforcement point:**

- `emg-auth-client` — `Principal` (subject, roles, attributes), `ServicePrincipalLike`
  (structural Protocol: client_id, roles, scopes), `AuthorizationRequest` (principal,
  resource_type, action, resource_attributes), `Decision` (outcome, reason, policy_id;
  `.allowed` property), `PolicyEnforcementPoint` (Protocol: `authorize(request) ->
  Decision`, "MUST be fail-closed").
- `emg-policy-engine` — `PolicyRule`/`PolicyConfig` (pydantic schema: `resource_type`,
  `action`, `effect` allow|deny, `required_roles` any-of, `required_attributes` all-of
  for a human `Principal`, `required_scopes` any-of for a `ServicePrincipalLike`),
  `PolicyEngine.evaluate()` (pure, **default-deny, deny-overrides, fail-closed, not
  configurable**), `LocalPolicyEnforcementPoint` (the default PEP implementation),
  `load_policy_config`/`validate_policy_config` (missing file → empty/default-deny
  config, not an error; malformed existing file → error), `roles.ROLE_CATALOG` (a
  governed vocabulary of eight roles already seeded in Keycloak: `platform-user`,
  `investigator`, `decision-maker`, `knowledge-steward`, `service-account`,
  `svc-identity`, `svc-authorization`, `svc-audit` — **a vocabulary, not a second
  authorization mechanism**), `testing.py` (`AuthorizationScenario`/`assert_scenario`/
  `run_scenarios`, the shared authorization testing harness).
- `services/identity` — the only current adopter. `GET /authz/check` wires
  `LocalPolicyEnforcementPoint` as a FastAPI dependency
  (`policy_enforcement_point_dependency`), loads
  `config/policy.example.yaml` via `EMG_IDENTITY_POLICY_CONFIG_PATH`, and is
  explicitly documented as introspection only (*"always returns HTTP 200 ... it is
  not an enforcement gate"*). Its example policy file already contains a
  `resource_type: identity.diagnostics` / `action: read` rule using
  `required_attributes.classification_clearance: [INTERNAL, CONFIDENTIAL, SECRET]` —
  i.e. the existing `required_attributes` mechanism is already the intended future
  home for classification-clearance conditions.
- `services/authz` (the dedicated Module 5 PDP network service the Freeze names,
  §10/§11) remains `scaffolded` (`service.yaml`) — **no live authz microservice exists
  to call over the network.** The PEP is, today, exclusively an in-process library.
- No `services/gateway`/BFF exists. The Freeze's "gateway (coarse tenant)" enforcement
  tier (§16) has no implementation; each service (`audit`, `identity`,
  `knowledge-graph`) authenticates independently, by established, documented
  convention ("each service validates inbound machine tokens itself, no shared
  broker" — `emg_audit_service.authn` / `emg_knowledge_graph_api.authn`).

**Classification and domain-model fields:**

- `emg_common_types.Classification` (`UNCLASSIFIED`/`INTERNAL`/`CONFIDENTIAL`/`SECRET`)
  is defined platform-wide; its own docstring states *"this enum defines the label
  vocabulary only — enforcement logic belongs to Module 5 (Authorization)."*
- `MemoryNode.classification` and `MemoryEdge.classification`
  (`libs/python/emg-memory-graph`) both exist, default `INTERNAL`, and are already
  exposed as a `list_entities` filter parameter in the Query API
  (`classification: Classification | None`) — but filtering by a caller-supplied query
  parameter is not the same as *enforcing* a caller's clearance against it, and no
  such enforcement exists anywhere today.
- No per-resource **ownership** field exists on `MemoryNode`/`MemoryEdge` (only
  `source: SafeLabel` — an ingestion-source label, not a principal reference — and
  `EvidenceRef.source_principal`, which records who *supplied evidence*, not who
  *owns* the resulting node/edge). ADR-016's "ownership" is an org-accountability
  register (which executive/team owns a module/API), unrelated to per-resource
  access control. **"Ownership" is therefore excluded from this ADR's decision-input
  list** (§9) — it is not supported by repository evidence as a per-resource
  authorization attribute.
- No **purpose-of-access** field exists anywhere in the repository.

**Error and status-code conventions:**

- `emg_errors.catalog` defines exactly five error types today: `ValidationError`,
  `AuthorizationError` (used platform-wide for *authentication* failure → 401, per
  every existing mapping in `audit`, `identity`, `knowledge-graph`),
  `NotFoundError`, `ConflictError`, `UpstreamServiceError`. **There is no error type
  or status-code mapping for "authenticated but not permitted" (403) anywhere in this
  repository.** (`services/identity/src/emg_identity/audit_pipeline.py` mentions the
  literal number 403 once, in an unrelated comment about which upstream HTTP statuses
  are "permanent" for retry logic — not a raised error or a route mapping.)
- `emg_knowledge_graph_api/errors.py`'s `ERROR_STATUS_MAP` maps `AuthorizationError`→
  401, `EntityNotFoundError`/`EdgeNotFoundError`/`RevisionNotFoundError`→404,
  `InvalidQueryError`/`QueryLimitExceededError`/`PathDepthExceededError`/
  `InvalidTemporalFilterError`→422, `UnsupportedHistoryCapabilityError`→501.

**Frozen platform principles directly governing this decision**
(`EMG_PRODUCT_ARCHITECTURE_FREEZE.md`):

- §16 Permission Model (frozen): *"Enforcement points: gateway (coarse, tenant) + authz
  PDP (fine, per-object) + persistence (row/edge scoping). Every decision audited.
  Deny-by-default."* RBAC baseline roles: Viewer, Contributor, Steward, Admin,
  Auditor. ABAC attributes: classification, department, evidence-source, tenant,
  node-type, decision-sensitivity. *"Classification clearance: enforced (not merely
  filtered) on every read — the current top security-debt item, promoted to a launch
  blocker."*
- §17 Multi-tenancy Model (frozen): shared-schema, `tenant_id`-scoped, *"enforced at
  persistence + PDP."* *"No domain-model change is permitted to achieve isolation —
  only persistence/PDP configuration."*
- §22 Security Architecture (frozen): defense in depth, item 3: *"Authz PDP — RBAC +
  ABAC + classification enforcement, deny-by-default, on every read/write."*
- §9/§11: the domain core performs no I/O; one writer/reader per store; cross-context
  change flows through APIs, never direct store access.

## 6. Decision Drivers

- Repository-driven only: every input and mechanism this ADR names must already exist
  in the codebase (an explicit instruction for this task).
- Reuse, never duplicate, `emg-auth-client`/`emg-policy-engine` — the Freeze already
  names this pairing as the PDP; a second mechanism would contradict §16.
- Do not touch `emg_knowledge_graph` (Query Engine/domain layer), `GraphStore`,
  persistence, Neo4j projection, or `MemoryGraph`/`MemoryNode`/`MemoryEdge` — this
  sprint (per its own explicit scope) must not change Query Engine behavior.
- Do not require infrastructure that does not exist (`services/authz` is scaffolded;
  there is no gateway) — the decision must work with today's repository, not a future
  one.
- Leave classification enforcement, mutation authorization, and audit reconciliation
  to their own ADRs (026/027/028) — this ADR only answers "can this authenticated,
  tenant-resolved caller perform this read operation," nothing about *which specific
  nodes/edges* it may see within that operation.

## 7. Considered Options

**A. Enforce inside `emg_knowledge_graph` (the domain/application layer).**
Rejected. `KnowledgeGraphApplication`'s contracts (`commands.py`) carry no
principal/role/scope field, and its own dependency-boundary test forbids importing
authorization or persistence concepts into that package. Adding a principal parameter
would reopen ADR-024 (which this task is explicitly told not to reopen) and would
entangle a pure, storage-agnostic query layer with an HTTP-authentication concern that
belongs one layer up. `emg_knowledge_graph` is consumed by exactly one caller today
(`emg_knowledge_graph_api`, per OBS-A-002) — nothing is gained by pushing the decision
down into it.

**B. Call a live, network `services/authz` PDP.**
Rejected for this ADR (reserved for later, §9). `services/authz` is `scaffolded`
(`service.yaml`) — there is no HTTP surface to call. Building one would be new
infrastructure and a materially larger change than "add an authorization decision to
an existing service," and would contradict the Freeze's own description of `authz` as
a distinct, not-yet-built service boundary. `PolicyEnforcementPoint` is already a
`Protocol`, so this remains a pure dependency-injection swap whenever `services/authz`
is actually built — not something this ADR needs to build prematurely.

**C. Introduce a bespoke, Knowledge-Graph-specific authorization mechanism
(e.g., a hand-rolled role check inside each route).**
Rejected. This is precisely the "second authorization framework" the objective
prohibits, and it would abandon the one property `emg-policy-engine` already
guarantees platform-wide: default-deny, deny-overrides, fail-closed, testable via the
shared `emg_policy_engine.testing` harness.

**D. Reuse `emg-auth-client`/`emg-policy-engine` in-process, wired at the HTTP layer,
exactly as `services/identity`'s Sprint 4 reference integration already does — but
made a genuine enforcement gate, not an introspection endpoint.**
**Selected.** Matches an established, working, already-tested pattern with zero new
frameworks; requires no infrastructure that doesn't exist; keeps `emg_knowledge_graph`
untouched; and is a strict superset of identity's Sprint 4 wiring (same dependency
function shape, same config-loading convention, same default-deny posture) rather than
a new one.

## 8. Decision

### 8.1 Security boundary

The security boundary is the Knowledge Graph service's own HTTP ingress
(`emg_knowledge_graph_api`'s FastAPI app). There is no gateway/BFF service in this
repository today (§5) to hold that boundary instead — exactly as `audit` and
`identity` already independently authenticate at their own HTTP boundary, by
documented convention. This ADR does not propose introducing a gateway; if one is
built later (Freeze §16's "coarse, tenant" tier), it becomes an *additional*,
outer boundary, not a replacement for this one — services must remain able to enforce
authorization even when called directly, the same defense-in-depth posture Freeze §22
already states.

### 8.2 Authorization boundary

The authorization boundary is **one decision per HTTP request, at the operation
level**: "may this authenticated caller, already resolved to tenant `T`, perform
action `read` against resource type `knowledge-graph.<X>`?" It is **not** a per-node
or per-edge decision (that is classification enforcement, ADR-026's explicit scope —
see §16) and it is **not** a cross-tenant decision (tenant isolation is a separate,
already-solved, structural mechanism — §8.4, §8.8). This ADR implements the
"operation-level RBAC/ABAC" slice of Freeze §16's three-tier enforcement model
(gateway / PDP / persistence); it is the PDP tier, scoped to "which operations,"
not the persistence tier's "which rows."

### 8.3 Where authorization is enforced

**HTTP layer, via a FastAPI dependency, evaluated before the route calls into
`KnowledgeGraphApplicationDep`.** Justification, mapped against the four options the
task asked to weigh:

- **Domain layer:** rejected (Option A, §7) — no principal concept exists there, and
  it must not be added without reopening ADR-024.
- **Application layer (`KnowledgeGraphApplication`):** same reasoning — its contracts
  are principal-free by design (ADR-024), and nothing routes through it except the
  HTTP layer today.
- **Policy Engine alone (as a standalone gate with no HTTP integration):** insufficient
  on its own — something must call it, per-request, with the request's actual
  resource_type/action, and reject before the query executes. That caller is
  necessarily at the HTTP layer, since only the HTTP layer currently holds the
  `CallerContext` (principal + tenant) and knows which route (hence which
  resource_type/action) is being invoked.
- **Combination — selected.** The HTTP layer (a new FastAPI dependency in
  `emg_knowledge_graph_api`, alongside `TenantContextDep`) constructs the
  `AuthorizationRequest` and calls the already-existing
  `emg_auth_client.PolicyEnforcementPoint` / `emg_policy_engine.LocalPolicyEnforcementPoint`
  (Policy Engine layer) to get the `Decision`; the HTTP layer then enforces it (raises
  on deny). This is the identical two-party split (HTTP wiring + Policy Engine
  evaluation) `services/identity`'s Sprint 4 integration already established — this
  ADR's only change to that pattern is making the HTTP side an actual gate instead of
  an introspection response.

### 8.4 Information required for every authorization decision

Restricted to what repository evidence already supports (§5):

| Input | Source | Status |
| :--- | :--- | :--- |
| Tenant | `CallerContext.tenant` (`TenantId`) | Already resolved by `authn.py`; used for query scoping, not (today) a `PolicyRule` condition — see §8.8 for why. |
| Principal | `CallerContext.principal` (`ServicePrincipal`: `client_id`, `roles`, `scopes`) | Already resolved by `authn.py`. Only machine callers exist in this service today (§5); `AuthorizationRequest.principal` is typed as `AuthorizedIdentity = Principal \| ServicePrincipalLike`, so a future human path needs no change here. |
| Role | `ServicePrincipal.roles` | Already carried on the token; matched against `PolicyRule.required_roles` (any-of), exactly as `emg-policy-engine` already implements. |
| Scopes | `ServicePrincipal.scopes` | Already carried on the token; matched against `PolicyRule.required_scopes` (any-of). |
| Resource type + action | The specific route being called (e.g. `knowledge-graph.entity` / `read`) | New, but directly modeled on the existing `identity.diagnostics` / `read` convention (`policy.example.yaml`) — not a new mechanism. |
| Classification | `MemoryNode.classification` / `MemoryEdge.classification` | Exists in the domain model; **not** plumbed into any `AuthorizationRequest.resource_attributes` by this ADR — reserved for ADR-026 (§9). |
| Ownership | — | **Excluded.** No per-resource owner field exists (§5). Not repository-evidenced; not included. |
| Purpose of access | — | **Excluded.** No such field exists anywhere in the repository. Not included. |

`resource_attributes: dict[str, str]` on `AuthorizationRequest` is already open-ended
and unused by this ADR beyond what the table above states — it is the extension seam
for §9, not populated here.

### 8.5 Operations requiring authorization

Every existing route in `emg_knowledge_graph_api/routers/knowledge_graph.py`, mapped
to a `(resource_type, action)` pair chosen to align with the named Query API
capabilities the Freeze itself already lists (§19: *"decision/why/lineage/evidence/
temporal/affected-projects/shortest-path"*):

| Route | resource_type | action |
| :--- | :--- | :--- |
| `GET /entities/{id}` (`get_entity`) | `knowledge-graph.entity` | `read` |
| `GET /entities` (`list_entities`) | `knowledge-graph.entity` | `read` |
| `GET /edges/{id}` (`get_edge`) | `knowledge-graph.edge` | `read` |
| `GET /edges` (`list_edges`) | `knowledge-graph.edge` | `read` |
| `GET /entities/{id}/neighbors` (`list_neighbors`) | `knowledge-graph.neighbors` | `read` |
| `GET /paths/shortest` (`find_shortest_path`) | `knowledge-graph.path` | `read` |
| `GET /entities/{id}/history/{attr}` (`get_entity_history`) | `knowledge-graph.history` | `read` |

`neighbors`, `path`, and `history` are deliberately separate `resource_type`s from
`entity`/`edge` (rather than one blanket `knowledge-graph.graph`/`read`), so a future
policy can grant plain entity/edge lookup without also granting traversal or temporal
history — each is independently named in Freeze §19 and each has a materially
different disclosure profile (a path or neighbor set can reveal relationships a direct
entity/edge read would not).

Future mutation endpoints (ADR-027, out of scope here) must reuse this identical
mechanism with `action="write"` (or a similarly named action) against the same
`resource_type`s — not a separate authorization path.

### 8.6 Authorization-failure behavior

Three distinguishable outcomes, none of them new except the middle one:

- **401 (unchanged):** authentication failure — missing/malformed/invalid/expired
  token, or a token with no resolvable tenant claim. Already `AuthorizationError` →
  401 (`errors.py`). Unaffected by this ADR.
- **403 (new):** the caller is authenticated and tenant-resolved, but the Policy
  Engine's `Decision.outcome == "deny"` for this `(principal, resource_type, action)`.
  **A new error type is required** — `emg_errors` has no existing type for this
  outcome (§5); reusing `AuthorizationError` would overload its established,
  repository-wide 401 meaning and make every existing caller of that error type
  (audit, identity, knowledge-graph's own authn) ambiguous about which failure
  occurred. This ADR therefore specifies a new `PermissionDeniedError(EMGError)` in
  `emg_errors.catalog`, mapped to HTTP 403 in each adopting service's error map. This
  is filling a genuine, evidenced gap (§5), not introducing a second framework — it is
  one new leaf in the existing `EMGError` hierarchy, handled by the same centralized
  exception handler every service already uses.
- **404 (unchanged):** an entity/edge id that does not exist *within the caller's own
  tenant* — already `EntityNotFoundError`/`EdgeNotFoundError` → 404. Cross-tenant
  "not found" is not a real case this API can produce: `GraphQueryScope.tenant` is
  bound from the verified token, so a caller cannot even construct a request naming
  another tenant (§8.8) — there is no other-tenant object for it to be denied or
  told doesn't exist. This is a structural (type-level) guarantee, not a
  response-shape decision.

**Should a permission denial be disguised as 404 (indistinguishable responses)?**
**No, not by default.** No existing service in this repository disguises a denial as
"not found" — `/authz/check`'s own docstring insists on being honest about what it
decided rather than obfuscating; Freeze §16/§22 both require *"every decision
audited,"* which presumes the decision is a distinguishable, loggable event, not a
deliberately ambiguous response. A 403 is auditable, matches the one existing repo
precedent for treating decisions as first-class artifacts (`Decision.reason`, always
populated, "for consistent audit logging" per its own docstring), and does not
introduce a new obfuscation convention no other service follows. **Reserved
exception, not decided here:** a future SECRET-classification object where even
confirming existence is itself sensitive may warrant 404-for-403 specifically for
that object — that is a classification-driven decision belonging to ADR-026, and this
ADR explicitly leaves room for it (§9) rather than deciding it now.

### 8.7 Integration with the existing Policy Engine

No new framework. Concretely, this ADR specifies that `emg_knowledge_graph_api`:

1. Depends on `emg-auth-client` (already an implicit dependency via
   `TenantContextDep`'s `CallerContext`/`ServicePrincipal` shapes — formalizing the
   authorization contract types is additive) and `emg-policy-engine` (new declared
   dependency, mirroring `services/identity`'s existing dependency on the same
   package).
2. Gains its own `policy_enforcement_point_dependency()` / `PolicyEnforcementPointDep`
   — the same function shape as `services/identity/src/emg_identity/dependencies.py`'s
   dependency of the same name — loading a Knowledge-Graph-owned
   `config/policy.example.yaml` via a new `EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH`
   setting, following the exact `EMG_IDENTITY_POLICY_CONFIG_PATH` convention
   (safe-default: a missing file yields an empty, default-deny `PolicyConfig`, never a
   startup failure).
3. Builds one `AuthorizationRequest(principal=caller.principal, resource_type=...,
   action="read")` per request (§8.5's table), using the `caller: TenantContextDep`
   the route already receives — no new authentication mechanism, only a new use of
   data already resolved.
4. Calls `pep.authorize(request)` and raises the new `PermissionDeniedError` when
   `not decision.allowed` — the exact "each service is responsible for its own `if not
   decision.allowed: raise ...`" pattern the identity README already documents as the
   intended, not-yet-adopted convention. **This makes the Knowledge Graph service the
   first real enforcement adopter of the platform's PEP/ABAC stack**, not merely the
   second reference integration.
5. Introduces no new role vocabulary unless a genuine gap is found in
   `emg_policy_engine.roles.ROLE_CATALOG`'s existing eight roles during
   implementation (Group C task, §15) — the expectation, pending that check, is that
   `platform-user`/`investigator`/`decision-maker`/`knowledge-steward` (human) and
   `svc-*`/`service-account` (machine) already cover the Knowledge Graph's caller
   population, since it currently accepts only machine `ServicePrincipal`s drawn from
   the same registered-service population `identity`'s example policy already
   enumerates.

### 8.8 Tenant isolation vs. authorization: evaluation order

Strict, four-step order, per request:

1. **Authenticate** the Bearer token (signature, issuer, audience, expiry). Failure →
   401. *(existing, unchanged)*
2. **Resolve tenant** from the verified token's `tenant_claim`. Failure (claim absent
   or invalid) → 401. *(existing, unchanged)*
3. **Authorize** `(principal, resource_type, action)` via the PEP. Failure (deny) →
   403 `PermissionDeniedError`. *(new, this ADR)*
4. **Execute** the query, tenant-scoped via `GraphQueryScope(tenant=caller.tenant,
   ...)`. A missing id within that tenant → 404. *(existing, unchanged)*

Authorization is deliberately evaluated **after** tenant resolution and **before**
query execution:

- **After tenant resolution**, because no `PolicyRule` in the existing schema
  (`emg_policy_engine.rules.PolicyRule`) has a tenant field — tenant is not a policy
  condition today, it is a structural, type-level scope (`TenantId` threaded through
  `GraphStore`). Evaluating authorization first would require inventing a tenant-aware
  policy condition that doesn't exist in the repository, which this ADR is not
  authorized to do; evaluating it after tenant resolution means the PEP only ever
  needs to answer "can this principal do this operation," never "in which tenant,"
  keeping the two mechanisms orthogonal exactly as they are structured today.
- **Before query execution**, to satisfy default-deny/fail-closed (Freeze §16, §22)
  precisely: a denied caller must never cause a persistence read (Postgres/Neo4j) to
  even begin. This also avoids doing avoidable I/O for a request that will be
  rejected regardless.

Tenant isolation itself is **not** re-decided by this ADR — it remains exactly what
ADR-024/Sprint 7.4 already built: a caller's token can only ever resolve to its own
tenant, so cross-tenant access is structurally unrepresentable, not merely
policy-denied. This ADR adds a gate *inside* one tenant's boundary, not a new
mechanism for the boundary itself.

### 8.9 Reserved extension points (not implemented by this ADR)

- **Classification-based ABAC (ADR-026).** `AuthorizationRequest.resource_attributes`
  is already an open `dict[str, str]` — reserved key `classification`, populated from
  `MemoryNode.classification`/`MemoryEdge.classification`, to be matched against a
  future `required_attributes.classification_clearance` condition — precisely the
  shape `services/identity`'s own example policy file already anticipates. Not
  populated or enforced here.
- **Other Freeze §16 ABAC attributes** (`department`, `evidence-source`, `node-type`,
  `decision-sensitivity`) — same reservation, same mechanism (`resource_attributes`),
  no schema change required when they are eventually adopted.
- **Per-object (node/edge-level) authorization**, as opposed to this ADR's
  per-operation level — ADR-026's scope. Deliberately not designed here since it
  likely changes *where* the PEP is called (once per returned row vs. once per
  request) and that performance/architecture trade-off belongs to that ADR, not this
  one.
- **Human `Principal` login path** for the Knowledge Graph API — `AuthorizationRequest.
  principal` is already typed generically (`AuthorizedIdentity = Principal |
  ServicePrincipalLike`); adding a human path later requires no change to this ADR's
  authorization call site.
- **A live, network `services/authz` PDP** — `PolicyEnforcementPoint` is already a
  `Protocol`; swapping `LocalPolicyEnforcementPoint` for a remote-PDP-backed
  implementation later is a dependency-injection change, not a redesign, mirroring how
  `GraphStore`'s in-memory/Postgres swap already works.
- **Mutation API authorization (ADR-027)** — same PEP call, same `resource_type`s,
  `action="write"` (or equivalent), `resource_attributes` extended with pre-write
  resource state once mutation exists.
- **A gateway/BFF coarse-tenant tier** (Freeze §16) — if built later, becomes an
  additional outer boundary; this ADR's HTTP-layer enforcement remains the inner,
  defense-in-depth gate regardless (§8.1).

## 9. Non-Goals (explicit, restated)

This ADR does **not** design: classification enforcement (ADR-026), the mutation API
or its authorization (ADR-027), audit reconciliation (ADR-028), Search, GraphRAG, or
AI Orchestration. It does not modify `emg_knowledge_graph`, `GraphStore`,
`MemoryGraph`/`MemoryNode`/`MemoryEdge`, REST API contracts (beyond the additive
authorization gate and new 403 mapping), persistence logic, or the Neo4j projection.
It does not stand up `services/authz` as a network service or a gateway/BFF.

## 10. Rationale Summary

Every decision above is chosen to be the smallest change that closes the "no
enforcement anywhere" gap using only mechanisms the repository already built and
tested: `emg-auth-client`'s contract, `emg-policy-engine`'s evaluator, and
`services/identity`'s Sprint 4 wiring pattern as the concrete template. The one
genuinely new artifact — `PermissionDeniedError`/403 — is justified by an explicit,
grep-verified absence of any existing 403 convention (§5), not by preference; every
other input, boundary, and ordering decision traces to a specific, cited file already
in the tree.

## 11. Alternatives Considered (consolidated)

See §7 for the four architectural placement options. Additional narrower alternatives
considered and rejected:

- **Reusing `AuthorizationError` for both 401 and 403.** Rejected — would make every
  existing 401 site ambiguous and would require callers to inspect message text to
  distinguish authentication from authorization failures, defeating the point of a
  stable `error_code`.
- **Disguising 403 as 404 platform-wide.** Rejected as a default — no repository
  precedent, and contradicts the audited-decision requirement (Freeze §16/§22).
  Reserved as a possible future, classification-specific exception (§8.9), not a
  general rule.
- **Evaluating authorization before tenant resolution.** Rejected — `PolicyRule` has
  no tenant condition today; doing so would require inventing one, which is outside
  this ADR's repository-driven mandate.
- **Per-node/edge authorization now, instead of per-operation.** Rejected for this
  ADR — no classification-clearance matching exists yet (that's ADR-026), and
  per-object evaluation is a materially different performance/architecture question
  than "gate the operation."

## 12. Consequences

**Positive:**

- The Knowledge Graph Query API goes from "any authenticated caller in its own tenant
  can do anything" to "any authenticated caller in its own tenant can do what its
  role/scope is granted for" — a genuine, evidenced closure of a real gap, using
  existing, already-tested machinery.
- `services/identity`'s PEP/ABAC stack gets its first real enforcement adopter,
  proving the pattern end-to-end beyond introspection — directly useful evidence for
  Module 5's eventual `services/authz` build-out and for ADR-027's mutation API, which
  can reuse this same mechanism verbatim.
- No architectural surface this sprint was told to protect (`emg_knowledge_graph`,
  `GraphStore`, persistence, Neo4j) changes at all.

**Negative / costs:**

- A new error type (`PermissionDeniedError`) is a small, permanent addition to a
  shared library (`emg_errors`) — every future service gains it whether or not it
  uses it, though this is consistent with how `ConflictError`/`UpstreamServiceError`
  were already added speculatively for future use.
- Every route gains one additional dependency call (PEP evaluation) — a small,
  synchronous, in-process cost (no network call, since `LocalPolicyEnforcementPoint`
  is pure/local), but non-zero.
- A misconfigured or missing `EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH` file means
  **default-deny of every request** (existing `emg_policy_engine.loader` behavior for
  a missing file is an *empty* config, and an empty config denies everything) — this
  is the correct fail-closed behavior, but it is an operational sharp edge: forgetting
  to ship a policy file breaks the service entirely rather than silently allowing
  access. Documented in `services/knowledge-graph/README.md`.

**Neutral / deferred risk:**

- Because only machine `ServicePrincipal`s call this API today, the initial policy
  file leans on `required_roles`/`required_scopes` (the machine track) almost
  exclusively; the human `required_attributes` track will be exercised only once a
  human-facing path exists. This is expected, not a defect.

## 13. Migration Impact

No data migration. No schema change to any store. No change to `GraphStore`,
persistence migrations (V001/V002), or Neo4j. Impact is confined to:

- **`services/knowledge-graph` only** — no other service's behavior changes.
- **Additive HTTP-layer change**: a new dependency runs before existing routes
  execute; existing successful (allowed) requests are unaffected in shape or status
  code. Existing denied-by-authentication (401) and not-found (404) behavior is
  unchanged.
- **New failure mode for existing callers**: any current caller whose role/scope
  would not satisfy the initial policy file's rules will begin receiving 403 where it
  previously received 200. This is the entire point of the change; the initial policy
  file grants the roles most plausibly needing Knowledge Graph read access
  (`investigator`, `decision-maker`, `knowledge-steward`, `service-account`) — see §18
  for the role-catalog review that informed this.
- **Deployment**: one new environment variable
  (`EMG_KNOWLEDGE_GRAPH_API_POLICY_CONFIG_PATH`) and one new config file
  (`services/knowledge-graph/config/policy.example.yaml`), following the identity
  service's existing pattern — plus a small `Dockerfile` addition (§18) so the
  packaged example resolves inside the running container.
- **Rollback**: reverting is a pure code/config revert (remove the dependency call and
  the new error mapping) — no persisted state depends on this change.

## 14. Repository Evidence Index

Primary files inspected to ground this ADR:

- `services/knowledge-graph/src/emg_knowledge_graph_api/authn.py`,
  `routers/knowledge_graph.py`, `errors.py`, `store.py`, `dependencies.py`, `config.py`
- `services/knowledge-graph/src/emg_knowledge_graph/commands.py` (`GraphQueryScope`)
- `libs/python/emg-auth-client/src/emg_auth_client/{decision,pep,principal,protocol,
  service_principal_protocol}.py`
- `libs/python/emg-policy-engine/src/emg_policy_engine/{engine,rules,loader,pep,
  roles,testing}.py`, README.md
- `libs/python/emg-common-types/src/emg_common_types/classification.py`
- `libs/python/emg-platform-core/src/emg_platform_core/identity/{tenant,principal}.py`,
  `ports/graph_store.py`
- `libs/python/emg-memory-graph/src/emg_memory_graph/{nodes,edges,evidence}.py`
- `libs/python/emg-errors/src/emg_errors/{catalog,base}.py`
- `services/identity/README.md`, `config/policy.example.yaml`,
  `src/emg_identity/routers/authz.py`, `service_registry.py`
- `services/audit/src/emg_audit_service/authn.py` (`_RECOGNIZED_CLIENTS`)
- `services/*/service.yaml` (confirming `authz` remains scaffolded; no gateway
  service exists)
- `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9–§12, §16, §17, §19, §22
- `docs/architecture/EMG_ADR-016_Enterprise_Ownership_Registry.md`
- `docs/architecture/EMG_ADR-024_KNOWLEDGE_GRAPH_QUERY_ENGINE.md` (format template and
  ADR-024 contracts confirmed unchanged)
- `docs/architecture/EMG_ARCHITECTURE_DECISION_REGISTER.md` (OBS-A-002, two-package
  service structure — confirms `emg_knowledge_graph_api` is the correct, sole layer to
  extend)

## 15. Compliance Checklist

- [x] Repository-driven: every mechanism named already exists in the tree.
- [x] No new authorization framework introduced (`emg-auth-client`/`emg-policy-engine`
      reused as-is).
- [x] `emg_knowledge_graph` (Query Engine/domain layer) contracts unchanged.
- [x] `GraphStore`, persistence, Neo4j projection unchanged.
- [x] Classification enforcement, mutation API, audit reconciliation, Search,
      GraphRAG, AI explicitly out of scope.
- [x] Ownership and purpose excluded from decision inputs (no repository evidence).
- [x] Tenant/authorization evaluation order explicitly defined.
- [x] Extension points for ADR-026/027 explicitly reserved, not implemented.

## 16. Group C Implementation Task List (as approved)

1. **C1** — Add `PermissionDeniedError(EMGError)` to `emg_errors.catalog`.
2. **C2** — Declare `emg-auth-client`/`emg-policy-engine` as dependencies.
3. **C3** — `policy_enforcement_point_dependency()`/`PolicyEnforcementPointDep`,
   mirroring `services/identity`.
4. **C4** — Initial `config/policy.example.yaml`, minimum permissions, default deny.
5. **C5** — `require_permission()` authorization helper, fail-closed.
6. **C6** — Wire into all seven routes.
7. **C7** — Map `PermissionDeniedError` to HTTP 403.
8. **C8** — Role-catalog review; extend only on evidenced gap.
9. **C9** — Full authorization test suite (allowed/denied/missing policy/missing
   role/missing scope/default deny).
10. **C10** — Deployment documentation (policy config, fail-closed behavior,
    deployment requirements).
11. **C11** — Update `ARCHITECTURE_STATUS.md`/`EMG_ARCHITECTURE_DECISION_REGISTER.md`.
12. **C12** — Verify the dependency-boundary test still passes.

## 17. Related Documents

ADR-016 (Enterprise Ownership Registry — Module 5 owner: CISO), ADR-020 (Knowledge
Ingestion), ADR-021 (Enterprise API Strategy), ADR-022/023/024 (Knowledge Graph
Revision Build Workflow / Revision History & Navigation / Query Engine),
`EMG_PRODUCT_ARCHITECTURE_FREEZE.md`, `EMG_ARCHITECTURE_DECISION_REGISTER.md`
(OBS-A-002), `docs/engineering/sprint-4-design.md` (PEP/ABAC contract-vs-implementation
split rationale), `docs/engineering/security-limitations.md`, Knowledge Graph
Integration Closure implementation specification (Groups C–F).

## 18. Implementation Notes (added post-implementation, 2026-07-27)

Group C implemented §8 exactly as decided. Two small, evidence-driven adjustments
were required at implementation time; neither changes any decision recorded in §8 —
both are implementation-detail fixes needed to make §8's decisions actually
type-check and run, discovered only once real code was written against them (per
this sprint's instruction to "stop and report" rather than silently redesign):

1. **`ServicePrincipal.service_name` (a missing field, not a new capability).**
   `emg_auth_client.ServicePrincipalLike` — the structural Protocol
   `AuthorizationRequest.principal` is typed against — requires a `service_name`
   field, and both `services/audit` and `services/identity`'s own `ServicePrincipal`
   types already carry it. `emg_knowledge_graph_api.authn.ServicePrincipal` (Sprint
   7.4) did not, a pre-existing gap never caught before because nothing in this
   service called into `emg_auth_client`/`emg_policy_engine` until this ADR. Fixed by
   adding `service_name: str = ""` to that dataclass. Unlike `audit`/`identity`,
   which resolve this field from their own registry-style allow-list of recognized
   `client_id`s, this service has no such registry (see item 2), so the field
   defaults to an empty string rather than a resolved value — an honest reflection
   of current capability, not a fabricated identity.
2. **Role-catalog review (C8): no gap found, but a related gap flagged.**
   `emg_policy_engine.roles.ROLE_CATALOG`'s existing eight roles were reviewed
   against the Knowledge Graph's caller population. No new role was added.
   `platform-user` (baseline, no job-function tie) was deliberately **not** granted
   in `config/policy.example.yaml`; `investigator`, `decision-maker`,
   `knowledge-steward` (human) and `service-account` (machine) were, as the roles
   whose descriptions plausibly justify Knowledge Graph read access. Separately, and
   NOT fixed by this ADR: no service client is registered anywhere (`identity`'s
   `SERVICE_REGISTRY`, the Keycloak realm seed, or an equivalent in this service) as
   a Knowledge Graph API consumer, and this service's `TenantServiceTokenValidator`
   performs no registry-based allow-list check at all (unlike `audit`'s
   `_RECOGNIZED_CLIENTS` or `identity`'s `SERVICE_REGISTRY`) — any validly-signed
   token for the configured realm/audience is accepted. Granting `service-account`
   in the policy file is therefore the least-privilege choice available in the
   *existing* catalog, not a statement that a specific consumer has been reviewed.
   Introducing such a registry is flagged as a follow-up task, out of this ADR's
   authorized scope.

Also required, to make the deployed feature actually functional rather than a design
gap: `Dockerfile`'s runtime stage did not copy `services/knowledge-graph/config` into
the image at all (neither did `services/identity`'s own Dockerfile, for its
equivalent `config/*.example.yaml` files — a pre-existing, platform-wide gap, not
introduced here). Fixed for this service only by adding a `WORKDIR /app` plus a
`COPY --from=base` of the `config` directory into the runtime image, so the packaged
example policy resolves at the same relative path `Settings.policy_config_path`
expects, without requiring every deployment to override the environment variable
just to get default (still dev-only) behavior.
