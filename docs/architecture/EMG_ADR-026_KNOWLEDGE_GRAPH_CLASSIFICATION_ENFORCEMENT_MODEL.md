# ADR-026 (Revision 2) — Knowledge Graph Classification Enforcement Model

**This is the first and only version of ADR-026 committed to this
repository.** A Revision 1 (standalone classification comparator, `scopes`-
literal machine clearance) was drafted, put through Architecture Review Round
1, and rejected on two of its three mechanisms — but Revision 1 itself was
never committed as a repository file; it existed only as an architecture-
review work product. This document is Revision 2: the corrected, Board-
approved design, incorporating all three amendments from that review. It is
self-contained — it does not require cross-referencing an uncommitted
Revision 1 draft — and is the authoritative architecture specification for
Group D.

---

## PART A — ADR-026 (Revision 2)

### 1. Title

Knowledge Graph Classification Enforcement Model — Per-Object Clearance
Gating via an Extended Policy Engine (Knowledge Graph Integration Closure,
Group D architecture specification)

### 2. Status

**Accepted (Revision 2).** Reviewed by the Architecture Board in Round 1
(three concerns raised against the original design), revised to incorporate
all three amendments, and accepted as the final architecture baseline for
Group D. No further design review is required before implementation,
subject to whatever standard code-review process Group D's pull requests go
through.

**Date:** 2026-07-27
**Deciders:** Principal Software Architect / Architecture Board (EMG
Platform), CISO (Accountable Owner, Module 5 — ADR-016 §1, item 2)
**Related:** ADR-024 (Knowledge Graph Query Engine), ADR-025 (Knowledge
Graph Tenant & Authorization Model), `EMG_PRODUCT_ARCHITECTURE_FREEZE.md`,
`EMG_ARCHITECTURE_DECISION_REGISTER.md`
**Explicitly does not supersede or reopen:** ADR-022, ADR-023, ADR-024
(Query Engine contracts, revision model, pagination/temporal semantics), or
ADR-025 (tenant/authorization model, evaluation order, PEP wiring). Both
remain repository fact, unchanged by this ADR.

### 3. Context

ADR-025 answers "may this authenticated, tenant-resolved caller perform this
operation at all" — one decision per request. It does not decide which
specific nodes and edges a permitted caller may see once inside an allowed
operation, and named that gap as this ADR's scope (ADR-025 §8.9, §8.6).

`EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §21 names this gap explicitly as the
platform's own top security-debt item: *"Classification clearance: enforced
(not merely filtered) on every read — the current top security-debt item,
promoted to a launch blocker."* `MemoryNode.classification`/
`MemoryEdge.classification` already exist (default `INTERNAL`); the existing
`ListEntitiesQuery.classification` filter is optional and caller-supplied —
exactly the "merely filtered" pattern the Freeze names as insufficient. No
code path in the repository compares a caller's clearance against an
object's classification and compels a result on that basis.

An initial design considered a standalone classification comparator living
outside `emg-policy-engine`, with machine-caller clearance carried as a
`ServicePrincipal.scopes` literal. Architecture review found that both
mechanisms worked against the platform's own already-documented design
invariants: (a) the repository's own stated position
(`emg_policy_engine/roles.py`: *"there is exactly one authorization
mechanism in EMG™"*; Freeze §22: classification enforcement is one function
of the Authz PDP, not a second mechanism beside it) requires classification
to be decided inside the Policy Engine, not beside it; and (b) the
Knowledge Graph service's own `authn.py` had already established the
correct precedent for "the platform needs one more piece of identity data"
— a dedicated claim (`tenant_claim`), not an overload of an existing field.
This ADR adopts both corrections.

### 4. Problem Statement

Decide, for the Knowledge Graph Query API's seven existing routes:

1. What classification enforcement means, and how it differs from ADR-025's
   authorization decision.
2. At which layer, and through which mechanism, a per-object clearance
   comparison is made.
3. At which point in the request lifecycle it occurs.
4. How list/neighbor/path/history traversal behaves when returned objects
   exceed the caller's clearance.
5. Shortest-path behavior when the single engine-computed path contains a
   node or edge above clearance.
6. Whether a caller can ever observe a historical value tied to a node whose
   classification exceeds their clearance.
7. Whether forbidden list objects are visibly excluded (an authorization
   failure) or silently absent.
8. How this reuses the existing ABAC vocabulary and evaluator, without a
   second authorization engine.
9. The evaluation order between ADR-025's authorization decision and this
   ADR's classification gate.
10. What extension points remain reserved, not designed.

### 5. Existing Architecture (repository evidence)

**Classification model (unchanged by this ADR):**
`emg_common_types.Classification(str, Enum)` —
`UNCLASSIFIED`/`INTERNAL`/`CONFIDENTIAL`/`SECRET`, vocabulary only, no
ordering defined on the enum itself. `MemoryNode.classification`/
`MemoryEdge.classification` exist independently on both types, both default
`INTERNAL`. Freeze §15: classification is an ontology-level concern,
*"enforced downstream by authz."* Freeze §21: classification is one ABAC
attribute among several (*"classification, department, evidence-source,
tenant, node-type, decision-sensitivity"*), not a bespoke mechanism. Freeze
§22: *"Authz PDP — RBAC + ABAC + classification enforcement, deny-by-default,
on every read/write"* — one layer, one mechanism, not two.

**Query Engine result-contract gaps (unchanged by this ADR; the reason
Amendment 3 exists):** `EntitySummary`/`EntityDetails` already expose
`classification` — no gap for `get_entity`/`list_entities`. `EdgeDetails`
(used by `get_edge`/`list_edges`) does not carry `classification`, though the
`_edge_details()` mapping function already holds the source `MemoryEdge` (and
therefore its `.classification`) in scope. `NeighborResult` carries the
neighboring entity's classification but not the connecting edge's.
`PathResult` carries only bare `node_ids`/`edge_ids`, no classification for
either. `EntityHistoryResult` carries no classification for the subject node
at the resolved revision. `KnowledgeGraphApplication`'s seven query methods
take no principal/clearance parameter (`emg_knowledge_graph/service.py`,
confirmed by direct reading); that package's own dependency-boundary test
forbids importing an authorization concept into it — the same frozen
boundary ADR-025 §8.3 already established.

**Authorization / Policy Engine surface — the evidence Amendments 1 and 2
directly act on:**

- `emg_auth_client.AuthorizationRequest.resource_attributes: dict[str, str]`
  already exists, documented as *"optional, resource-side context (e.g. the
  specific resource's own classification) a policy rule may condition on."*
  Prior to this ADR, `emg_policy_engine.engine.PolicyEngine.evaluate()`
  never read this field — `_conditions_satisfied`/`_human_conditions_satisfied`/
  `_service_conditions_satisfied` compared only `rule.required_roles`/
  `required_attributes`/`required_scopes` against `request.principal`. **This
  ADR's Amendment 1 closes that gap** (§8.2, §8.9) rather than routing
  around it — the gap was an implementation omission, not an architectural
  boundary.
- `emg_auth_client.Principal.attributes: dict[str, str]` already exists for
  human callers, and `services/identity/config/policy.example.yaml` already
  contains a working, tested `classification_clearance:
  [INTERNAL, CONFIDENTIAL, SECRET]` rule using it — the exact attribute-key
  convention this ADR reuses (§8.4).
- `emg_auth_client.ServicePrincipalLike` (Protocol), prior to this ADR, had
  **no `attributes` field** — only `client_id`, `roles`, `scopes`,
  `service_name`. Its own (pre-ADR) docstring stated this was *"Sprint 3
  design"*: *"machine identities carry no classification/department claims
  by Sprint 3 design."* All three concrete implementers
  (`services/identity/src/emg_identity/service_principal.py`,
  `services/audit/src/emg_audit_service/authn.py`,
  `services/knowledge-graph/src/emg_knowledge_graph_api/authn.py`) lacked
  any attributes-carrying field. Per ADR-025 §5, the Knowledge Graph API
  accepts only machine `ServicePrincipal` callers today — the one caller
  type this API currently supports had no repository-modeled way to carry a
  clearance value at all, prior to this ADR's Amendment 2.
- `services/knowledge-graph/src/emg_knowledge_graph_api/authn.py` already
  established, in this exact service, the correct precedent for adding a new
  piece of identity data a token doesn't carry yet: its own docstring
  describes extending *"the existing inbound-authentication convention ...
  with one new, minimal addition: a `tenant_claim`."* This ADR's Amendment 2
  follows that precedent for clearance rather than a scopes-literal
  convention.
- `emg_policy_engine.roles.ROLE_CATALOG`'s own docstring: *"there is exactly
  one authorization mechanism in EMG™: the ABAC `PolicyEngine` ... this
  catalog is [a vocabulary,] not a second authorization or enforcement
  mechanism."* This is the platform's own stated invariant Amendment 1
  brings classification enforcement into conformance with.
- ADR-025 §8.9 and §8.6 are the direct hand-off of this ADR's scope.

**Freeze principles governing this decision:** §21, §22 (as above); §15
(classification enforced downstream of the ontology/domain layer, i.e., not
inside `emg_knowledge_graph`/`emg-ontology`); §9 (domain core performs no
I/O, storage/consumer-agnostic — nothing assigns enforcement to the domain
layer).

### 6. Decision Drivers

- Repository-driven only — every mechanism named already exists, or is the
  smallest possible, explicitly-scoped extension of something that already
  exists.
- **One authorization mechanism.** `emg-policy-engine` is the platform's
  declared single evaluator (`roles.py`); this ADR's central purpose is to
  make classification enforcement conform to that invariant.
- Do not change `emg_knowledge_graph` (Query Engine/domain layer)
  *behavior* — traversal algorithms, pagination, and revision resolution
  remain exactly as ADR-024 defined them. Data *projection* (§8.3, Amendment
  3) is a distinct, narrower concern treated separately. `GraphStore`,
  persistence, and the Neo4j projection are untouched. `MemoryQueryEngine`'s
  algorithms are untouched.
- Do not redesign ADR-025 — its per-request authorization decision, PEP
  wiring, and evaluation order are fixed inputs this ADR composes with.
- Reuse the existing ABAC vocabulary and the existing `PolicyEnforcementPoint`
  → `PolicyEngine` → `Decision` pipeline (Amendment 1) and the existing
  `attributes`/dedicated-claim pattern already proven for `Principal` and for
  `tenant_claim` respectively (Amendment 2) — no new engine, no new config
  format, no new identity type beyond what those two patterns already
  establish.
- "Enforced, not merely filtered" (Freeze §21) remains the standard: the
  gate is mandatory and clearance-driven, never an optional, caller-selected
  query parameter.

### 7. Considered Options

**A. Push a `principal`/clearance parameter into `emg_knowledge_graph`'s
Query Engine methods and filter inside `MemoryQueryEngine`/`MemoryGraph`
traversal.**
Rejected. The Query Engine is frozen, has no principal concept, and Freeze
§15 assigns enforcement downstream of it.

**B. A dedicated, standalone classification comparator, external to
`emg-policy-engine`, invoked once per returned object.**
Considered and **rejected**. It works in isolation but contradicts the
platform's own stated "one authorization mechanism" invariant, cannot scale
to future Search/GraphRAG/AI classification enforcement without
duplication, and produces classification decisions with no `Decision`-
shaped audit trail (`reason`/`policy_id`), unlike every other decision this
platform's audit posture assumes is captured that way.

**C. Extend `PolicyEngine` so classification is evaluated through the
existing `PolicyEnforcementPoint` → `PolicyEngine` → `Decision` pipeline, by
adding `required_resource_attributes` to `PolicyRule` (symmetric to the
existing `required_attributes`) and having `PolicyEngine.evaluate()` compare
it against `AuthorizationRequest.resource_attributes` — which already exists
on the request type and was already documented as intended for exactly this
purpose.**
**Selected (Amendment 1).** This is additive to `emg-policy-engine`
(`PolicyRule` gains one new optional field; `PolicyEngine` gains one
symmetric comparison, mirroring the existing principal-attribute check
line for line) and does not change default-deny, deny-overrides, or
fail-closed semantics, which are orthogonal to which attributes a rule
inspects. `Classification`'s four-value domain does not require an ordinal
operator inside the engine: dominance is expressed as enumerated policy
data (a fixed, small table of clearance/classification pairs — at most ten
entries), exactly the same enumeration style
`services/identity/config/policy.example.yaml`'s existing
`classification_clearance` rule already uses on the principal side. This
option has a wider blast radius than Option B (it touches a shared library
consumed by `identity`, `audit`, and `knowledge-graph`, and reserved for the
future `authz` service), which is disclosed plainly in §13 rather than
minimized, but it is the only option that scales to future classification-
aware consumers without duplicating comparator logic, and the only option
that produces an auditable `Decision` for every classification check.

**D. A distinct dominance-rule schema type inside `emg-policy-engine`,
separate from `PolicyRule`'s existing role/scope/attribute matching.**
Considered and rejected: solves the same problem as Option C with more new
schema surface (a second rule type, a second matching code path) for no
proportional gain over reusing the existing symmetric-dict pattern.

### 8. Decision

#### 8.1 What classification enforcement is, and how it differs from ADR-025

ADR-025 answers *"may this caller perform this operation at all"* — one gate
per request, visible on denial (403). This ADR answers a different question,
per returned object: *"is this specific object's classification within this
caller's clearance?"* — evaluated after ADR-025's gate has already said yes.
The two mechanisms remain deliberately different in observability: an
ADR-025 denial is a visible, audited 403 (the existence of an operation-
permission boundary is not itself sensitive); a classification denial is
designed to be indistinguishable from the object not existing (§8.5),
because confirming a denied classified object's existence can itself leak
the fact classification protects.

#### 8.2 Where classification is enforced (Amendment 1 applied)

**HTTP layer in `emg_knowledge_graph_api`, immediately after each
`KnowledgeGraphApplication` query method returns and before the result is
mapped into a REST response — evaluated by calling the existing
`PolicyEnforcementPoint.authorize()`, once per returned object, exactly as
ADR-025 already wires it, with `resource_attributes={"classification":
obj.classification.value}` supplied on the request.**

This is not a second decision engine; there is no bespoke boolean function,
and no code path in `emg_knowledge_graph_api` that makes an authorization-
shaped decision outside the PEP. The full pipeline for every classification
check is:

```
emg_knowledge_graph_api (HTTP layer)
        |
        v
PolicyEnforcementPoint.authorize(AuthorizationRequest(
    principal=caller.principal,
    resource_type="knowledge-graph.<entity|edge|neighbors|path|history>",
    action="read",
    resource_attributes={"classification": <object>.classification.value},
))
        |
        v
PolicyEngine.evaluate()   # now also matches required_resource_attributes
        |
        v
Decision(outcome, reason, policy_id)
```

This is the same `PolicyEnforcementPoint`/`PolicyEngine`/`Decision` contract
ADR-025 already integrated for operation-level authorization — reused a
second time, for a second, additional, per-object question, never
replaced or duplicated. Every classification decision is now a proper
`Decision`, auditable exactly the way every RBAC decision already is.

Evaluated against the same four placement options ADR-025 already weighed:
**Query Engine** and **persistence** remain rejected for the reasons already
established (frozen, no principal concept, Freeze §15 assigns enforcement
downstream). **Policy Engine** is the *evaluation* location, not merely a
*vocabulary* source. **HTTP layer** is the correct location for *invoking*
the PEP per object and *acting on* its `Decision` (pruning, hiding, or
denying per §8.5–§8.7) — identical in kind to how the HTTP layer already
invokes the PEP once per request for ADR-025.

#### 8.3 When enforcement occurs (request lifecycle)

Extending ADR-025 §8.8's four-step order with one additional step:

1. **Authenticate** (401). *(ADR-025, unchanged)*
2. **Resolve tenant** (401). *(ADR-025, unchanged)*
3. **Authorize the operation** via the PEP (403 `PermissionDeniedError`).
   *(ADR-025, unchanged)*
4. **Execute the query** against `GraphStore`/`GraphRevisionReader` through
   the unmodified `KnowledgeGraphApplication`/`MemoryQueryEngine`. *(unchanged)*
5. **Enforce classification**: for each returned object, call
   `PolicyEnforcementPoint.authorize()` with `resource_attributes` carrying
   its classification (§8.2); apply §8.5–§8.7 per endpoint.
6. **Map and serialize** the classification-filtered result into the REST
   response. *(unchanged)*

Classification enforcement happens after query execution (the Query Engine
has no pre-execution clearance-filtering capability to integrate with) and
before serialization (a denied object's field values must never reach the
wire format).

#### 8.4 Resolving a caller's clearance (Amendment 2 applied)

- **Human `Principal` callers:** `principal.attributes.get(
  "classification_clearance")`, parsed as one `Classification` value — the
  exact convention `services/identity`'s own example policy already uses.
- **Machine `ServicePrincipalLike`/`ServicePrincipal` callers** (the only
  caller type the Knowledge Graph API supports today, per ADR-025 §5):
  **`ServicePrincipalLike` and every concrete `ServicePrincipal` (`identity`,
  `audit`, `knowledge-graph`) gain an `attributes: dict[str, str]` field**,
  additive and default-valued (`field(default_factory=dict)`), mirroring
  `Principal.attributes` exactly — full structural parity between human and
  machine identity types, closing an asymmetry the `ServicePrincipalLike`
  Protocol's own (pre-ADR) docstring already named as a point-in-time
  "Sprint 3 design" simplification, not a permanent invariant.
- **Population mechanism:** a caller's clearance is read from a **dedicated
  JWT claim** (e.g. `classification_clearance`), extracted into
  `ServicePrincipal.attributes["classification_clearance"]` at token-validation
  time, in each service's own `authn.py`, following the exact precedent
  `services/knowledge-graph/src/emg_knowledge_graph_api/authn.py` already
  established for `tenant_claim` (*"this module extends the existing
  inbound-authentication convention ... with one new, minimal addition"*).
  This is not a `scopes` literal, has no ambiguous-parsing failure mode.
- **Default:** a caller with no resolvable `classification_clearance`
  attribute — human or machine — is assigned the platform's lowest
  clearance, `UNCLASSIFIED`, fail-closed, consistent with default-deny
  (Freeze §22). This default must be applied explicitly at the point each
  claim is extracted (every token/claim-issuance path this ADR's Amendment 2
  and its Group D Phase 1 Remediation touch populates the literal string
  `"UNCLASSIFIED"` rather than omitting the key), because `PolicyRule`
  matching (`required_attributes`/`required_resource_attributes`) has no
  "attribute absent" special case of its own — an absent key simply fails
  every allow-list match, which would satisfy neither an allow rule nor a
  deny rule keyed on the literal value `"UNCLASSIFIED"`. Keeping this default
  at the claim-extraction layer, rather than teaching the engine an
  "absent means lowest tier" special case, keeps `PolicyEngine` itself
  generic and declarative (Appendix ADR-026A, principle 1).
- **PolicyEngine evaluation:** `PolicyEngine._service_conditions_satisfied`
  is extended to evaluate `rule.required_attributes` against
  `principal.attributes` for a `ServicePrincipalLike` caller, using the exact
  same all-of matching `_human_conditions_satisfied` already performs for a
  human `Principal` — the same code shape, applied to both identity kinds.
  This retires the prior hard `return False` whenever `required_attributes`
  was non-empty for a service principal; that branch was correct only under
  the now-superseded "machine identities carry no attributes" assumption.

#### 8.5 The uniform denial principle: hidden objects are indistinguishable from absent objects

An object whose classification the caller's resolved clearance does not
dominate is treated, in every observable way, identically to an object that
does not exist. No status code, error message, count, or field distinguishes
"exists but you're not cleared" from "genuinely does not exist / has no
value / is unreachable." This is deliberately different from ADR-025's
visible 403, for the same reason as before: RBAC-denial existence is not
sensitive; classification-denial existence can be.

| Endpoint | Existing "not found / empty / no value" shape reused |
| :--- | :--- |
| `get_entity` | `EntityNotFoundError` → 404 |
| `list_entities` | Object silently absent from the page |
| `get_edge` | `EdgeNotFoundError` → 404 |
| `list_edges` | Object silently absent from the page |
| `list_neighbors` | Neighbor (and its connecting edge) silently absent |
| `find_shortest_path` | `PathResult(found=False)` |
| `get_entity_history` | `EntityHistoryResult(item=None)` |

No new error type, status code, or response field is introduced for the
denial path — every endpoint's pre-existing "nothing here" shape is reused.

#### 8.6 Traversal, path, and history behavior

- **`list_neighbors`:** prune. Each neighbor evaluated independently — hidden
  if the neighboring entity's classification exceeds clearance, or if the
  connecting edge's classification exceeds clearance.
- **`list_entities`/`list_edges`:** prune, same mechanism.
- **`find_shortest_path`:** the engine computes exactly one true shortest
  path over the complete graph (frozen, no exclusion parameter). If any node
  or edge on that path exceeds clearance, the result is `found=False` — not
  an alternate path (would require a Query Engine algorithm change, out of
  scope), not a visible denial. Disclosed limitation: a caller may receive
  `found=False` even though a different, fully-visible path might
  independently exist; this ADR does not promise otherwise without a future
  ADR-024 amendment (§10).
- **`get_entity_history`:** gated on the subject node's classification at
  the resolved revision (a single, well-defined value — classification is
  not `TemporalHistory`-tracked). If not cleared, `item=None`, identical in
  shape to "the attribute had no value at that moment."

#### 8.7 List endpoints: pruned, not surfaced as authorization failures

Forbidden objects are filtered, never surfaced as a distinguishable
authorization failure. Pagination already tolerates fewer-than-requested
results as an ordinary outcome; a caller cannot tell, from the response
alone, whether zero objects matched or several matched and were pruned.

#### 8.8 Evaluation order

ADR-025's authorization decision (operation-level, via the PEP) always
precedes this ADR's classification gate (per-object, via the same PEP, now
also carrying `resource_attributes`). An operation-level deny short-circuits
before any query executes and before any per-object classification check
runs. The two remain a strict, sequential composition of two decisions
through the *same* PEP contract — not a merged decision, and not two
different mechanisms — which is itself one further argument in favor of
Amendment 1: both gates now produce the identical `Decision` shape through
the identical pipeline, differing only in what `resource_type`/`action`/
`resource_attributes` each call supplies.

### 9. Non-Goals

This ADR does not design: the Mutation API or its authorization (ADR-027),
audit reconciliation (ADR-028), Search, GraphRAG, or AI Orchestration. It
does not modify `emg_knowledge_graph`'s query *algorithms*, `GraphStore`,
`MemoryGraph`/`MemoryQueryEngine` internals, persistence, or the Neo4j
projection. It does not redesign ADR-025's authorization model, PEP wiring,
or evaluation order. It does not introduce a scripting/expression language
into `emg-policy-engine`, or any policy concept beyond
`required_resource_attributes` (see Appendix, ADR-026A).

### 10. Reserved Extension Points

Need-to-know, compartments, project clearance, mission tags, and cross-domain
access remain reserved, not designed. No such concepts exist anywhere in the
repository's domain model today. Per Appendix ADR-026A, each requires its
own future ADR — this ADR commits the Policy Engine extension to symmetry
(§8.2, §8.4) precisely so a future ADR for any of these can reuse the same
`required_resource_attributes` mechanism without a second engine, but does
not design any of them now. Query-Engine-aware shortest-path (computing a
path that only traverses visible nodes) remains reserved, requiring a future
ADR-024 amendment. A machine-caller clearance/client registry (mirroring
`identity.SERVICE_REGISTRY`) remains reserved, the same still-open gap
ADR-025 §18 already flagged.

### 11. Rationale Summary

Amendment 1 resolves the single most consequential architecture-review
finding: the repository already declares `emg-policy-engine` as its one
authorization mechanism and already documents `resource_attributes` as
intended for resource-side classification context — a standalone comparator
would work against both statements rather than completing them. Amendment 2
resolves the second: this exact service already established the correct
pattern (a dedicated claim, not an overloaded field) for exactly this kind
of need. Amendment 3 (below) confirms the original DTO-extension proposal is
correct, scoped as a projection change, not a behavioral one.

### 12. Alternatives Considered (consolidated)

See §7 for the four primary options. Additional alternatives rejected:
exposing classification denials as 403 uniformly with ADR-025 (rejected —
conflates two differently-sensitive failure modes); computing an alternate
classification-safe shortest path (rejected — requires a Query Engine
algorithm change); a distinct dominance-rule schema type inside
`emg-policy-engine` separate from `PolicyRule` (rejected — more schema
surface than reusing the symmetric-dict pattern, §7 Option D).

### 13. Consequences

**Positive:**

- Closes the Freeze's own launch-blocking security-debt item for the one
  live classification-bearing read surface in the platform today.
- Classification enforcement now conforms to, rather than works around, the
  platform's declared "one authorization mechanism" invariant — every
  classification decision is a proper, audited `Decision`.
- `Principal`/`ServicePrincipal` are now structurally symmetric on
  attributes — a consistency gain independent of classification, reusable
  by any future ABAC attribute (department, evidence-source, node-type,
  decision-sensitivity — Freeze §21) for machine callers, not just this one.
- Zero changes to `emg_knowledge_graph` *behavior*, `GraphStore`, persistence,
  Neo4j, or ADR-025's authorization model.

**Negative / costs:**

- **Wider blast radius than a Knowledge-Graph-local comparator.**
  `emg-policy-engine` and `emg-auth-client` are shared libraries consumed by
  `identity`, `audit`, and `knowledge-graph` today, and reserved for the
  future `authz` service. This change must be reviewed and tested against
  all current consumers, not scoped as Knowledge-Graph-local, and touches
  three concrete `ServicePrincipal` dataclasses plus the shared
  `ServicePrincipalLike` Protocol (§8.4) rather than one.
- **Every current caller defaults to `UNCLASSIFIED` clearance** until its
  token issuance is updated to include the new `classification_clearance`
  claim — since most existing data defaults to `INTERNAL` classification,
  this remains a materially breaking visibility change for every existing
  caller the moment Group D Phase 2 ships this to HTTP.
- `find_shortest_path` can under-report reachability (§8.6) — disclosed
  limitation, not a defect.
- Per-request cost: one additional `PolicyEnforcementPoint.authorize()` call
  per returned object — pure, in-memory, no network I/O (the current
  `LocalPolicyEnforcementPoint` implementation), negligible relative to query
  execution itself.

**Neutral / deferred risk:**

- No compartment/need-to-know/project-clearance/mission-tag/cross-domain
  concept exists yet (§10, ADR-026A) — this ADR's mechanism remains
  deliberately narrow (one ABAC attribute, `classification`), easy to extend
  later via the same symmetric `required_resource_attributes` pattern
  without redesign, but protecting only this one dimension today.
- **Human clearance provisioning is an identity-issuance concern, not a
  Policy Engine concern (§14, "Identity provisioning requirement").** This
  ADR's `PolicyEngine`/`ServicePrincipalLike` mechanism is symmetric between
  human and machine callers by construction (§8.4), but that symmetry only
  has real effect once *both* sides' clearance is actually populated
  end-to-end from an authoritative source (Keycloak) through to
  `Principal.attributes`/`ServicePrincipal.attributes`. This is an identity-
  provisioning completeness requirement this ADR depends on, not a Policy
  Engine design question — see Part F.

### 14. Migration Impact

No data migration; no persisted-store schema change; `MemoryNode.classification`/
`MemoryEdge.classification` values require no backfill. Impact is confined
to:

- **`libs/python/emg-policy-engine`** — additive `required_resource_attributes`
  field on `PolicyRule`; additive, symmetric matching logic in `PolicyEngine`.
- **`libs/python/emg-auth-client`** — additive `attributes` on
  `ServicePrincipalLike`.
- **`services/identity`, `services/audit`, `services/knowledge-graph`** —
  additive `attributes: dict[str, str] = field(default_factory=dict)` on each
  service's own `ServicePrincipal` dataclass; each service's own `authn.py`
  gains extraction of the new `classification_clearance` claim, following
  the existing `tenant_claim`-style pattern.
- **`services/knowledge-graph`** — the additive `emg_knowledge_graph/results.py`
  DTO fields (§8, Amendment 3 / Appendix), the new HTTP-layer wiring
  (§8.2), and deployment documentation covering the new claim requirement.
- **Identity provisioning requirement:** any deployment wishing its existing
  human users and service clients to retain current visibility must
  configure the new `classification_clearance` claim in its Keycloak token
  issuance — for human users, via a protocol mapper projecting the
  `classification_clearance` user attribute into the access token; for
  service clients, via the equivalent machine-token claim configuration —
  before or immediately upon relying on this ADR's enforcement, otherwise
  every caller silently drops to `UNCLASSIFIED`-only visibility (§13).
- **Rollback:** a pure code revert (remove the `resource_attributes` matching
  branch, the `attributes` fields, and the DTO field additions) — no
  persisted state depends on this change.

### 15. Repository Evidence Index

- `libs/python/emg-common-types/src/emg_common_types/classification.py`
- `libs/python/emg-memory-graph/src/emg_memory_graph/{nodes,edges}.py`
- `services/knowledge-graph/src/emg_knowledge_graph/{commands,results,service}.py`
- `services/knowledge-graph/src/emg_knowledge_graph_api/{authn,authorization,
  dependencies,errors,routers/knowledge_graph}.py`
- `libs/python/emg-auth-client/src/emg_auth_client/{decision,pep,principal,
  protocol,service_principal_protocol}.py`
- `libs/python/emg-policy-engine/src/emg_policy_engine/{engine,rules,roles}.py`
- `services/identity/src/emg_identity/service_principal.py`
- `services/audit/src/emg_audit_service/authn.py`
- `services/identity/config/policy.example.yaml` (source of the
  `classification_clearance` attribute-key convention, and the enumeration
  style Amendment 1 reuses on the resource side)
- `docs/product/EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9, §15, §16, §21, §22
- `docs/architecture/EMG_ADR-024_KNOWLEDGE_GRAPH_QUERY_ENGINE.md`
- `docs/architecture/EMG_ADR-025_KNOWLEDGE_GRAPH_TENANT_AUTHORIZATION_MODEL.md`
  §8.6, §8.9
- `docs/architecture/EMG_ARCHITECTURE_DECISION_REGISTER.md` (OBS-A-003)

### 16. Compliance Checklist

- [x] Repository-driven: every mechanism named already exists or is the
      smallest additive extension of something that already exists.
- [x] `emg-policy-engine` remains the platform's single authorization
      mechanism — no second engine introduced or retained.
- [x] `emg_knowledge_graph` query *algorithms*, `GraphStore`, persistence,
      Neo4j projection unchanged.
- [x] ADR-025's authorization model, PEP wiring, and evaluation order
      unchanged.
- [x] Mutation API, audit reconciliation, Search, GraphRAG, AI explicitly
      out of scope.
- [x] Need-to-know, compartments, project clearance, mission tags,
      cross-domain access reserved, not designed (Appendix ADR-026A).
- [x] Policy Engine remains declarative — no scripting/expression language
      introduced (Appendix ADR-026A).
- [x] The `emg_knowledge_graph/results.py` DTO extension is scoped as a
      data-projection change, distinct from — and not requiring the same
      review weight as — a Query Engine behavioral change.

---

## PART B — Amendments Applied (relative to the originally considered design)

| Area | Originally considered | Adopted in this ADR |
| :--- | :--- | :--- |
| Classification decision mechanism | Standalone comparator function in `emg_knowledge_graph_api`, outside `emg-policy-engine` | `PolicyEnforcementPoint.authorize()` → `PolicyEngine.evaluate()` → `Decision`, the same pipeline ADR-025 already uses, extended with `required_resource_attributes` |
| Policy Engine involvement | Vocabulary/enum only; `resource_attributes` left unread | `resource_attributes` becomes a fully evaluated input; `PolicyRule` gains `required_resource_attributes`, symmetric to `required_attributes` |
| Dominance expression | A new, standalone rank-mapping utility outside the Policy Engine | Enumerated policy data (`required_resource_attributes` allow-lists), evaluated by the extended `PolicyEngine` — no ordinal operator added to the engine |
| Machine-caller clearance carrier | `ServicePrincipal.scopes` literal convention (`"clearance:secret"`) | `attributes: dict[str, str]` field on `ServicePrincipalLike`/`ServicePrincipal`, mirroring `Principal.attributes` |
| Machine-caller clearance source | Implicit, parsed from a `scopes` string | Dedicated JWT claim (e.g. `classification_clearance`), extracted the same way `tenant_claim` already is |
| `PolicyEngine._service_conditions_satisfied` | Hard-rejects any rule with `required_attributes` for a service principal | Evaluates `required_attributes` against `ServicePrincipalLike.attributes`, symmetric to the human-principal path |
| `emg_knowledge_graph/results.py` DTO additions | Proposed | Retained: an immutable-projection change, distinct in kind from traversal/pagination/revision logic, which remain untouched |
| Request lifecycle, evaluation order | Authenticate → tenant → authorize → execute → classify → serialize | As adopted |
| Denial principle | Hidden == absent, uniformly, at every endpoint | As adopted |
| Traversal / path / neighbor / history / list behavior | Prune (list/neighbors); `found=False` (path); `item=None` (history); 404 (single-object) | As adopted |
| Reserved extensions | Need-to-know, compartments, project clearance, mission tags, cross-domain | Formalized under Appendix ADR-026A governance rule (no automatic expansion — each requires its own ADR) |
| Blast radius | Confined to `services/knowledge-graph` | Explicitly spans `libs/python/emg-policy-engine`, `libs/python/emg-auth-client`, and all three current `ServicePrincipal` implementers (`identity`, `audit`, `knowledge-graph`) — disclosed as a real cost of the corrected architecture |

---

## PART C — Appendix: ADR-026A — Policy Engine Extension Principles

This appendix governs how the Policy Engine extension introduced by
Amendment 1 may be used, both by Group D and by any future work that reuses
`required_resource_attributes`. It is part of this ADR's authority, not a
separate decision.

**1. Policy Engine remains declarative. No scripting language. No arbitrary
expressions.** `required_resource_attributes` is a `dict[str, list[str]]`
allow-list match, structurally identical to `required_attributes` — data,
not code. This extension does not introduce, and must never be used to
justify introducing, an expression language, a scripting hook, or any
form of caller-supplied or dynamically-evaluated logic into `PolicyConfig`
or `PolicyEngine.evaluate()`. Every future condition this engine gains must
remain expressible as declarative, enumerable rule data.

**2. `required_resource_attributes` is symmetric with `required_attributes`.
No separate policy model.** The resource side of a policy rule is evaluated
by the same kind of match (all-of, allow-list) as the principal side,
against the same `PolicyRule` type, inside the same `PolicyEngine.evaluate()`
method, producing the same `Decision` type. Classification is not special-
cased inside the engine as its own concept — it is simply one
`resource_attributes` key (`"classification"`) among any number of future
keys this same mechanism could carry. No parallel schema, no second rule
type, no engine-level concept of "classification" as distinct from any
other resource attribute.

**3. Future concepts require independent ADRs. No automatic expansion.**
Need-to-know, compartments, mission tags, project clearance, and cross-domain
access are not authorized, implied, or pre-approved by this ADR merely
because the `required_resource_attributes` mechanism could technically carry
them. Each remains reserved (§10) and requires its own future ADR — evaluating
its own repository evidence, its own semantics, and its own consequences —
before any of it is implemented, even though, mechanically, it would reuse
the same symmetric attribute-matching capability this ADR introduces.

---

## PART D — Group D Implementation Task List, with Phase Boundaries

The standalone-comparator implementation approach considered in review is
not included below in any form. Every task reflects the adopted architecture
only.

### Phase 1 — Platform Foundation (implemented)

1. **D1 — Extend `emg-policy-engine`.** Add `required_resource_attributes:
   dict[str, list[str]] = Field(default_factory=dict)` to `PolicyRule`
   (`rules.py`). Extend `PolicyEngine._conditions_satisfied`/
   `_human_conditions_satisfied`/`_service_conditions_satisfied`
   (`engine.py`) with a symmetric check: every named `resource_attributes`
   key must be present on `request.resource_attributes` with a value in the
   rule's allow-list, evaluated identically for both `Principal` and
   `ServicePrincipalLike` callers. Default-deny/deny-overrides/fail-closed
   semantics unchanged.
2. **D2 — Extend `emg-auth-client`.** Add `attributes: dict[str, str] =
   field(default_factory=dict)` to `ServicePrincipalLike`
   (`service_principal_protocol.py`, as a read-only `@property`, mirroring
   the existing members' declaration style).
3. **D3 — Extend all three `ServicePrincipal` implementers.** Add
   `attributes: dict[str, str] = field(default_factory=dict)` to
   `services/identity/src/emg_identity/service_principal.py`,
   `services/audit/src/emg_audit_service/authn.py`, and
   `services/knowledge-graph/src/emg_knowledge_graph_api/authn.py`'s
   `ServicePrincipal` dataclasses.
4. **D4 — Extend `PolicyEngine._service_conditions_satisfied`.** Replace the
   prior hard `return False` on any non-empty `rule.required_attributes` for
   a service principal with an evaluation against
   `ServicePrincipalLike.attributes`.
5. **D5 — Add the `classification_clearance` JWT claim extraction for
   machine tokens.** In each of `services/identity`, `services/audit`, and
   `services/knowledge-graph`'s own `authn.py`, extract a
   `classification_clearance` claim from the verified token payload into the
   caller's `attributes` dict, following the `tenant_claim` pattern. A
   missing or malformed value resolves to the literal `"UNCLASSIFIED"`
   (§8.4) rather than an absent key.
6. **D6 — Author the enumerated classification policy data.** Extend
   `services/knowledge-graph/config/policy.example.yaml` with
   `required_resource_attributes` deny rules expressing clearance dominance
   for each of the five Knowledge Graph `resource_type`s.

**Phase 1 Remediation (this addendum's own subject — see Part F):** three
blocking gaps found during independent audit of the Phase 1 implementation
were remediated: (a) human `Principal` clearance provisioning was
end-to-end broken (Keycloak token-endpoint metadata was being read where
verified access-token claims were required, and no protocol mapper emitted
`classification_clearance` into the token at all) — fixed; (b) this
document was missing from the repository — fixed by this commit; (c) a
dependency-boundary CI check false-failure for `services/knowledge-graph`'s
documented two-package structure (OBS-A-002) — fixed in the checker, not by
weakening the check.

### Phase 2 — Knowledge Graph Integration (not begun)

7. **D7 — Extend `emg_knowledge_graph/results.py` (DTO projection only, per
   Amendment 3/Appendix).** Add `classification: Classification` to
   `EdgeDetails`; add the traversed edge's classification to
   `NeighborResult`; add a per-node/per-edge classification record to
   `PathResult`; add the subject node's classification to
   `EntityHistoryResult`. No change to `service.py`'s traversal, pagination,
   or revision-resolution logic.
8. **D8 — Implement the HTTP-layer classification-enforcement module.** One
   function per result shape, each calling the existing
   `PolicyEnforcementPointDep` with `resource_attributes={"classification":
   <object>.classification.value}` per object, applying §8.5's uniform
   denial principle via each endpoint's existing not-found/empty/no-value
   shape.
9. **D9 — Wire the module into all seven routes.** Applied after
   `KnowledgeGraphApplication` returns and before response mapping, composed
   strictly after ADR-025's existing `require_permission` dependency, never
   replacing it.
10. **D10 — Update deployment documentation.** Document the new
    `classification_clearance` claim requirement (both human and machine),
    the fail-closed `UNCLASSIFIED` default for callers without it, and the
    migration requirement for existing deployments' Keycloak token issuance.
11. **D11 — Full test suite.** Per-endpoint pruning tests (list/neighbors),
    shortest-path-blocked tests, history-blocked tests, get_entity/get_edge
    404-on-classification tests, dominance-boundary tests, default-
    `UNCLASSIFIED`-for-unresolved-clearance tests, and a regression test
    confirming ADR-025's 403 still fires before any classification logic
    runs for an unauthorized caller.
12. **D12 — Verify boundaries.** Confirm the existing `emg_knowledge_graph`
    dependency-boundary test still passes unmodified; confirm the
    `results.py` field additions introduced no principal/authorization
    concept into `emg_knowledge_graph` itself; confirm no scripting/
    expression capability was introduced into `PolicyConfig`/`PolicyEngine`.
13. **D13 — Update governance records.** Update
    `ARCHITECTURE_STATUS.md`/`EMG_ARCHITECTURE_DECISION_REGISTER.md` to
    record this ADR as fully implemented (Phase 1 + Phase 2), and to record
    Appendix ADR-026A's three governing principles as the standing rule for
    any future `required_resource_attributes` reuse.

**Phase boundary rule:** Phase 2 must not begin before Phase 1 (including
its remediation, Part F) has been independently reviewed and approved.
Nothing in Phase 1 wires classification enforcement into live HTTP traffic;
`services/knowledge-graph/config/policy.example.yaml`'s classification deny
rules are validated only as policy data until D8/D9 land.

---

## PART E — Identity Provisioning Requirement

This ADR's symmetry guarantee (§8.4: human and machine callers carry
clearance identically, both defaulting fail-closed to `UNCLASSIFIED`) is
only true end-to-end once each side's clearance is actually populated from
an authoritative source through to the object `PolicyEngine` evaluates:

- **Machine callers:** `classification_clearance` JWT claim → each
  service's own `authn.py` claim extraction (D5) → `ServicePrincipal.attributes`.
- **Human callers:** Keycloak user attribute `classification_clearance` →
  a Keycloak protocol mapper projecting that attribute into the verified
  access token → `services/identity`'s login flow decoding the *verified*
  access token claims (not unverified token-endpoint metadata) →
  `Principal.attributes`, with the same explicit fail-closed
  `"UNCLASSIFIED"` default applied whenever the claim is absent, empty, or
  not a string.

Both paths are required for this ADR's fail-closed guarantee to hold in
practice; an incomplete human-side path (no protocol mapper, or claims read
from the wrong place) silently defeats classification enforcement for every
human caller even though the Policy Engine mechanism itself is correct and
symmetric. See Part F for the remediation that closed this gap for Phase 1.

---

## PART F — Phase 1 Remediation Record (2026-07-27)

An independent audit of the completed Phase 1 implementation (D1–D6) found
three blocking issues, all remediated in the same change that added this
document to the repository:

1. **Human classification provisioning was broken end-to-end.**
   `services/identity/src/emg_identity/keycloak_client.py` assigned the
   OAuth token endpoint's own top-level JSON response (`access_token`,
   `expires_in`, `refresh_token`, …) directly as if it were the decoded
   claims of the access token itself. `realm_access`, `classification_clearance`,
   and `department` are claims carried *inside* the signed access token, not
   top-level token-endpoint fields — so this code path never actually read
   them, and the Keycloak realm seed had no protocol mapper emitting
   `classification_clearance` into the token in the first place. **Fixed:**
   the identity service now verifies the Keycloak-issued access token via
   the realm JWKS (mirroring the existing `ServiceTokenValidator` trust
   path) and reads the resulting *verified* claims; a protocol mapper was
   added to the realm seed; a missing, empty, or non-string
   `classification_clearance` claim now resolves explicitly to the literal
   `"UNCLASSIFIED"`, never an absent key, matching the machine-token
   behavior D5 already established.
2. **This document did not exist.** Every Phase 1 source file referenced it
   by name; it had never been committed. Fixed by this commit.
3. **A dependency-boundary CI false failure.** `tools/ci/check_implicit_dependencies.py`
   flagged `emg_knowledge_graph_api`'s import of its sibling
   `emg_knowledge_graph` package as an undeclared external dependency
   (`emg-knowledge-graph`) — a checker limitation, not a real boundary
   violation: `services/knowledge-graph` is a documented (OBS-A-002),
   intentional two-package-per-`pyproject.toml` component, and the checker's
   self-import exclusion assumed one package name per component. Fixed in
   the checker to recognize every package a component's `pyproject.toml`
   actually builds, not just the single name derived from `[project].name`.

None of these three fixes changes any decision recorded in Parts A–C above.
Phase 2 (D7–D13) remains not begun.
