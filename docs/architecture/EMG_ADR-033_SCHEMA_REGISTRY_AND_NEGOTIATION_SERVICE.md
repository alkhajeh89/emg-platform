I re-verified the disputed claims against the actual implementation before revising. Three of the review findings are confirmed by direct evidence, and two of my Revision 1 claims were factually wrong.

**Evidence gathered:**

- `V004__mutation_ledger.sql` (lines 64–96): `mutation_ledger` has **no** `effective_schema_version` column. It carries `command_schema_version smallint`, which ADR-030 Rev 4 §5.1 line 197 defines as *"the semantic command-envelope schema stored by this mutation. Initial value: 1"* — the internal command envelope, not the negotiated ontology version.
- `effective_schema_version` appears in exactly three non-test locations: the `PreparedMutation` field, the response-header assignment in `routers/mutations.py:72`, and one test asserting `"1.0.0"`. **It never reaches persistence.**
- `MutationReplayIntegrityError` in `atomic_mutation.py` (lines 143, 270) guards persisted *result/receipt document* schema versions; replay comparison at line 217 uses `fingerprint` + `command_schema_version`. Negotiated semantic versions are not involved.
- `SchemaNegotiator` has **no** consumer outside the mutation path (8 files, all mutation-related). No second production consumer exists.

**No files were created or modified. No code or pseudocode appears below.**

---

# ADR-033 Revision 2 — Schema Registry and Negotiation Service

**Status:** Accepted — Revision 2
**Extends:** ADR-032 · **Consumes without modifying:** ADR-027 Rev 5, ADR-029, ADR-030 Rev 4
**Date:** 2026-07-28

---

## 0. Revision Note and Retractions

Revision 2 preserves Revision 1's architecture: an authoritative catalog, a fail-closed boot gate, deterministic exact-version negotiation, and a bounded normalization step. Eight decisions are refined and two Revision 1 claims are **retracted as factually incorrect**.

| Retraction | Revision 1 claimed | Repository evidence | Correction |
|---|---|---|---|
| **RT-1** | The effective version "reaches the audit record through the existing path… available to ADR-030's ledger." | `mutation_ledger` has no such column. The value terminates at an HTTP response header. | §10.3 rewritten. Catalog generation and effective version are **observability-only** in v1. Durable ledger recording requires a separate ADR. |
| **RT-2** | ADR-030's replay integrity mathematically forces exact-version pinning. | Replay is keyed on `command_fingerprint` + `command_schema_version` (internal envelope, value `1`); the negotiated ontology version is not an input. | §D3 rejustified on four independent architectural grounds. Replay compatibility becomes **acceptance criterion AC-18**, to be verified against the implementation rather than asserted. |

One decision is **reversed**: D1 now selects service-local infrastructure rather than a shared library, because Revision 1's duplication argument rested on a *predicted* second consumer that repository evidence does not support.

---

## 1. Context and Scope

ADR-032 is Accepted and defines negotiation as policy. The contract is implemented (`SchemaNegotiator`, `MutationRequestPreparer`, `Preferred-Schema-Version` / `Effective-Schema-Version` headers). The composition root injects `_UnconfiguredSchemaNegotiator`, which fails closed unconditionally, so every mutation fails before command construction. ADR-033 supplies the missing authoritative component.

ADR-027 Rev 5 §16 (line 432) requires that "Schema negotiation follows ADR-032 before command construction," and §591 requires that handlers contain no schema-negotiation algorithm. Revision 2 satisfies both.

**Direction clarification.** ADR-032 §2.3 frames adapters as the Query Engine presenting stored data in a client's version (read path, outbound). The blocking gap is inbound: normalizing a client's older-version *intent* to canonical form. ADR-033 governs the write path only and leaves ADR-032's read-path semantics untouched.

---

## 2. Contract Impact — Stated Honestly

Revision 1 asserted that all application contracts remain byte-for-byte unchanged. That was overstated. The accurate position:

### 2.1 Narrow internal application-contract changes (acknowledged)

| Change | Nature | Justification |
|---|---|---|
| New application port `CompatibilityAdapterRegistry` | **Additive** — a new Protocol in `emg_knowledge_graph` | ADR-032 §2.3 mandates compatibility adapters; `SchemaNegotiationResult.adapter_required` is signalled today and consumed by nothing. Some port must consume it. |
| `MutationRequestPreparer` gains a normalization step and a second constructor dependency | **Extension** — behaviour and construction signature change; the negotiate-before-construct ordering is preserved | The pipeline requires a normalization stage; the preparer is the only component positioned between negotiation and construction. |
| `SchemaNegotiationError` gains a machine-readable failure code discriminator | **Additive** — the error type and its position in the hierarchy are preserved | Required by review item 10. |

These are internal contracts consumed only within the knowledge-graph service. They are not public API surface.

### 2.2 Preserved without modification

- Public mutation commands (`CreateEntityCommand`, `ReplaceEntityCommand`, `ReplaceRelationshipCommand`, `CloseRelationshipCommand`, `MergeEntitiesCommand`)
- Mutation request/response DTOs and `map_mutation_request`
- `MutationExecutionResult` and `MutationResponse`
- HTTP transport: routes, `Preferred-Schema-Version`, `Effective-Schema-Version`, status semantics
- `KnowledgeGraphApplication` and atomic mutation execution
- `SchemaNegotiator`, `SchemaNegotiationRequest`, `SchemaNegotiationResult` — unchanged in shape
- `PreparedMutation`, including its `effective_schema_version` field

---

## 3. Design Principles

| # | Principle |
|---|---|
| P1 | Move failure from request time to boot time. |
| P2 | Negotiation is a pure, total, in-memory function — no I/O, no unbounded parsing. |
| P3 | Determinism over convenience. |
| P4 | Fail closed. No automatic permissive fallback, ever. |
| P5 | Normalization may not create authority. |
| P6 | Catalog identity is deployment identity. |
| **P7** | **The catalog is the sole source of compatibility truth.** No runtime inference from identifier structure. *(new in Rev 2)* |

---

## 4. The Canonical Pipeline

Revision 1 described normalization inconsistently — as a pre-command transformer in §5.2 and as a command transformer in the §5.5 diagram. Revision 2 defines **one pipeline, used everywhere in this document without variation**:

```
  Request DTO  (already transport-validated)
        │
        ▼
  Schema Negotiation           consumes: requested version identifier
        │                      produces: NegotiationOutcome
        │                                { accepted contract version,
        │                                  compatibility classification,
        │                                  normalization required (bool) }
        ▼
  Compatibility Normalization  consumes: Request DTO + NegotiationOutcome
        │                      produces: Canonical Request Values
        ▼
  Canonical Request Values     same DTO family, canonical semantics
        │
        ▼
  Command Construction         map_mutation_request — UNCHANGED
        │
        ▼
  Validation                   command/domain validation — UNCHANGED
        │
        ▼
  Application Execution        KnowledgeGraphApplication — UNCHANGED
```

### 4.1 Compatibility normalization — architectural definition

> **Compatibility normalization is a pure, total transformation from a transport-validated Request DTO expressed in an accepted client schema version, to Canonical Request Values expressed in the canonical execution schema, within the same DTO family.**

**Consumes:** the validated Request DTO, and the NegotiationOutcome.
**Produces:** Canonical Request Values — the same DTO family and field domain, with every value carrying canonical-schema meaning.

**Structural properties:**

- **Identity when not required.** For Strict and Backward classifications, normalization is the identity transformation. It is a step that always runs, not a branch.
- **DTO-to-DTO only.** Normalization never observes, constructs, or transforms a command. Commands are constructed *after* normalization, from canonical values, by unchanged code.
- **Closed field domain.** It may not add or remove fields. Any difference requiring a field the DTO family does not have is by definition structural — ADR-032's "Migration required" or "Incompatible" class — and must cause negotiation to **fail**, not be normalized.
- **No authority.** It may not write any classification-, owner-, tenant-, or principal-bearing value (P5).
- **Pure.** No I/O, no graph reads, no clock, no randomness.

**Why the frozen DTO family is architecturally productive.** It supplies the only crisp boundary between *adaptable* and *breaking*: a difference expressible within the existing field domain is adaptable; anything else is a breaking change requiring migration. This is a durable invariant, not a scoping convenience.

**Naming.** The port retains the review's name `CompatibilityAdapterRegistry`; its members are **normalizers**, and this document uses "normalizer" throughout to prevent the Revision 1 ambiguity from recurring.

---

## 5. Architectural Decisions

### D1 — Placement *(reversed from Revision 1)*

| Option | Assessment |
|---|---|
| **A** Shared platform library + service adapter | Revision 1's choice. Justified by a predicted Query Engine consumer. **Repository evidence does not support it**: `SchemaNegotiator` has no consumer outside the mutation path, and the review has decided the Query Engine adopts the registry only after the mutation path is proven. Building a shared library for one consumer is speculative generality. |
| **B** Service-local infrastructure implementation in `emg_knowledge_graph_infrastructure` | Matches the existing composition precedent (`GraphResourceMetadataReader`, `LocalPolicyEnforcementPoint`). In-process, no new availability domain. Ports are preserved, so extraction later is a mechanical refactor with no application-layer change. |
| **C** Standalone registry microservice | Places a synchronous network dependency on every mutation, converting configuration risk into availability risk. |

**Decision: Option B — service-local infrastructure for Version 1.**

**Justification.** Revision 1 argued Option A on `GraphStore` duplication precedent. That precedent applies when two consumers *exist*; here the second is scheduled after v1 is proven. The correct sequencing is to prove the design with one consumer, then extract. Because the application depends only on ports, extraction is a later refactoring that changes no application contract — the cost of deferring is genuinely low, and the cost of premature generalization is a library shaped by one caller.

**Extraction trigger (recorded now, so it is not rediscovered):** when the Query Engine adopts negotiation, the catalog model, loader, validator, and lookup move to a shared library unchanged; the ports do not move.

### D2 — Authoritative Data Source *(unchanged)*

**Decision: a declarative, version-controlled catalog artifact, loaded and validated at process start.**

ADR-032 §2.1 requires published versions to be immutable and §2.5 requires three-party approval. Only a reviewed artifact under change control makes both mechanically enforceable. A database table would make published versions runtime-mutable, contradicting §2.1. Code constants would conflate policy with logic.

**Authoritative catalog contents:** the known version identifiers; each version's lifecycle state (§D4); deprecation and retirement instants; the canonical execution schema version; the **absolute** compatibility classification of each version against canonical (review decision, §11); the normalization requirement per version; retirement tombstones; and a catalog generation identifier.

### D3 — Exact-Version Negotiation *(retained; rejustified)*

**Decision: negotiation accepts only exact, fully-qualified published version identifiers.** No aliases, no partial pins, no ranges, no wildcards.

Revision 1's justification (RT-2) is withdrawn. The decision stands on four independent grounds:

1. **Deterministic execution.** The same request against the same deployment resolves identically, always. Any alias makes resolution a function of catalog state at request time.
2. **Stable client contracts.** ADR-032 §1 declares the schema a rigid public contract. A client pinned to an exact version has a contract; a client pinned to a floating alias has a subscription to unannounced change.
3. **Audit clarity.** The accepted contract version recorded in logs and metrics is meaningful only if it identifies one immutable schema. `latest` in an audit trail identifies nothing after the next release.
4. **Prevention of silent version adoption.** With an alias, a client's effective semantics change on a server deployment the client never observed. Adoption of a new version must be a deliberate client act.

**Additional benefit (not a justification):** exact matching makes negotiation a constant-time lookup with no parser, which bounds denial-of-service exposure (§12).

**Disclosed cost.** Clients do not automatically adopt additive minor versions. Mitigated by ADR-032 §2.2's mandatory deprecation window — a pinned version remains Published and fully supported throughout — and by the discovery surface (§10.4) publishing the recommended current version.

**`latest` is relocated, not abolished:** a discovery-time concept, never a negotiation input.

### D4 — Version Lifecycle in the Runtime Catalog *(narrowed)*

**Version 1 runtime catalog contains exactly three states.** Draft schemas exist in the governance process and remain **entirely outside runtime negotiation**; no runtime switch exposes them.

| State | ADR-032 term | Negotiable | Semantics |
|---|---|---|---|
| **Published** | Published | **Yes** | Immutable per ADR-032 §2.1. Fully supported. |
| **Deprecated** | Deprecated | **Yes — succeeds** | Supported, with a retirement instant. Deprecation is advisory, emitting a signal (§10). Rejecting Deprecated versions would collapse ADR-032's mandatory cooling-off period to zero. |
| **Retired** | Sunset | No — **permanent tombstone** | Rejected as `RETIRED_SCHEMA`. The identifier is retained permanently and never reused, so the server can distinguish "retired here" from "never existed here." |

**Unknown is not a state.** No version is ever *in* Unknown. It is the outcome of a lookup against an identifier absent from the catalog. This distinction is load-bearing for D5.

**Why Experimental was removed.** Revision 1 admitted Experimental versions are not covered by ADR-032's immutability guarantee. Negotiating against mutable content produces audit records that cannot be interpreted after the fact, and required an environment-conditional switch — the one thing that must never differ by environment. Draft schemas are validated in the governance process and in pre-production integration testing, neither of which requires runtime negotiability.

### D5 — Catalog as Sole Compatibility Authority *(new in Rev 2)*

**Decision: compatibility is determined exclusively by catalog lookup. No runtime ordering, comparison, or structural interpretation of version identifiers occurs.**

Revision 1 inferred a "Future version" outcome by ordering the requested identifier against canonical. That made the identifier's *structure* a runtime authority, competing with the catalog, and would silently break the moment identifier conventions changed (a real risk given the deferred schema-families question).

Consequences, stated plainly:

- **There is no "Future Version" failure mode.** An identifier absent from the catalog is `UNKNOWN_SCHEMA`, whatever it looks like.
- A client deployed ahead of its server receives `UNKNOWN_SCHEMA` rather than a distinct signal. **This is a real diagnostic loss**, accepted because the alternative reintroduces a competing authority. It is mitigated operationally: the discovery surface (§10.4) makes the supported set self-service, and the `UNKNOWN_SCHEMA` metric dimensioned by requested identifier makes a rollout-ordering error visible within one deployment window.
- SemVer remains meaningful — for **authoring and governance**, where a human assigns the absolute classification recorded in the catalog. It is simply not an input to the runtime algorithm.

### D6 — Normalizer Registry and the Boot Gate *(unchanged in substance)*

**Decision: a separate `CompatibilityAdapterRegistry` port, with a mandatory boot-time consistency gate.**

Keeping resolution out of `SchemaNegotiationResult` preserves that contract's shape. Its genuine weakness is split authority — the negotiator may assert normalization is required while the registry holds no normalizer. This is resolved structurally:

> **Boot gate.** For every catalog entry classified as requiring normalization, the registry must resolve **exactly one** normalizer. Zero or many is a startup failure. The process never becomes ready and receives no traffic.

Under this gate, "missing normalizer" and "ambiguous selection" are **not runtime failure modes**. They are deployment failures.

**Selection is exact-pair, single-step.** No chaining, no nearest-match. Chaining would make the closed-field-domain invariant non-obviously preserved across a chain; a genuine two-step transformation is authored as one normalizer for that pair.

**Registration is static and declarative**, derived from the same catalog artifact. No runtime discovery, no entry-point plugins — the installed normalizer set must be a reviewed artifact, not an environmental accident.

### D7 — Catalog Loading and Caching *(unchanged)*

**Decision: load once at process start; immutable for the process lifetime; changes require redeployment.**

Background refresh and hot reload both permit two replicas to hold different catalogs, so the same request resolves differently depending on which replica serves it — invisibly. Given that the accepted contract version is an audit signal, silent divergence is not an acceptable trade for rollout latency. Schema catalogs change on ADR-032's six-month timescale; propagation latency is the wrong axis to optimize.

**Consistency guarantees:** within a request, trivially consistent; within a process, immutable after boot; across a fleet during rollout, transiently divergent but **observable** via the catalog generation on every metric and health response; across a rollback, atomic with the deployment.

**Additive-only rollout rule.** A single catalog change may not both add a version and retire another. Retirement is always a separate, subsequent deployment, making every rollout window monotonic.

---

## 6. Negotiation Algorithm

Deterministic, total, side-effect-free, catalog-driven. Rules are evaluated in order; the first match terminates.

| # | Condition | Outcome | Failure code |
|---|---|---|---|
| 1 | Header absent or empty | Rejected **at transport**, before negotiation (unchanged existing behaviour) | — |
| 2 | Identifier is not a well-formed fully-qualified version identifier | Rejected | `MALFORMED_SCHEMA` |
| 3 | Identifier absent from catalog | Rejected | `UNKNOWN_SCHEMA` |
| 4 | Catalog state = Retired | Rejected | `RETIRED_SCHEMA` |
| 5 | Catalog classification = Migration required, or Incompatible | Rejected | `INCOMPATIBLE_SCHEMA` |
| 6 | Catalog classification requires normalization | **Accepted**; normalization mandatory | — |
| 7 | Catalog state = Deprecated, classification compatible | **Accepted** + deprecation signal | — |
| 8 | Catalog state = Published, classification Backward or Strict | **Accepted** | — |

No rule inspects identifier ordering or structure beyond well-formedness (D5). Rules 5–8 read the catalog's absolute classification directly.

### 6.1 Two distinct schema concepts

Revision 1 conflated these. Revision 2 separates them permanently.

| | **Accepted Schema Contract** | **Canonical Execution Schema** |
|---|---|---|
| Meaning | The schema version the server accepted from the client, and under which the client's request was interpreted | The single schema version the server's internal model implements |
| Audience | **Client-facing** | **Internal only** |
| Value | Always exactly the version the client requested, on success | A single deployment-wide constant from the catalog |
| Varies per request | Yes | No |
| Exposed as | The `Effective-Schema-Version` response header | Metrics, structured logs, health/discovery surface |
| Never | Silently substituted | Returned to a client as their accepted contract |

### 6.2 `Effective-Schema-Version` — definitive statement

> **The `Effective-Schema-Version` response header carries the Accepted Schema Contract: the schema version under which the server interpreted this client's request. On every successful mutation it equals the version the client sent in `Preferred-Schema-Version`. It never carries the Canonical Execution Schema.**

Properties:

1. Always present and non-empty on success; never an alias.
2. Server-determined and authoritative (ADR-032 §2.4), never inferred client-side.
3. **Equals the requested version on every success — including when normalization ran.** Normalization changes how the server *interprets* the request internally; it does not change *which contract the client was accepted under*.
4. Reproducible: identical request + identical deployment ⇒ identical header value.
5. **Observability-only in Version 1.** It is not persisted. See §10.3 and RT-1.

**Why this is the correct semantics.** Revision 1 returned the canonical version in the normalization case, which told a client its contract had been changed to something it never requested — indistinguishable, from the client's view, from a silent downgrade. Under Revision 2, a success always confirms *"your stated contract was accepted."* Rejection is the only outcome that ever tells a client its version was not honoured.

**Naming tension, disclosed.** The header name predates this distinction and reads more like the internal concept than the client contract. The review requires retaining it, and renaming a shipped header is a breaking transport change. The name is retained; §6.2 is its normative definition. Recorded as an accepted residual.

**Compatibility with the existing test suite:** `test_stage4_phase3.py:206` asserts `prepared.effective_schema_version == "1.0.0"` for a request preferring `1.0.0`. Under Revision 2's semantics this assertion holds unchanged.

### 6.3 Worked outcomes (canonical execution schema = `2.1.0`)

| Client sends | Catalog | Outcome | Header returned | Code |
|---|---|---|---|---|
| `2.1.0` | Published, canonical, Strict | Accept | `2.1.0` | — |
| `2.0.0` | Published, Backward | Accept | `2.0.0` | — |
| `1.4.0` | Deprecated, Backward, retires in 4 months | Accept + deprecation signal | `1.4.0` | — |
| `1.2.0` | Published, normalization required | Accept, normalize | `1.2.0` | — |
| `1.0.0` | Published, Migration required | Reject | — | `INCOMPATIBLE_SCHEMA` |
| `0.9.0` | Retired tombstone | Reject | — | `RETIRED_SCHEMA` |
| `3.0.0` | Absent from catalog | Reject | — | `UNKNOWN_SCHEMA` |
| `9.9.9` | Absent from catalog | Reject | — | `UNKNOWN_SCHEMA` |
| `latest` | — | Reject | — | `MALFORMED_SCHEMA` |
| `2` | — | Reject | — | `MALFORMED_SCHEMA` |
| *(absent header)* | — | Reject at transport | — | *(not in taxonomy)* |

Rows 7 and 8 are deliberately identical: D5 removed the structural inference that previously distinguished them.

### 6.4 Ambiguity

Structurally impossible at runtime: identifiers are unique keys in an immutable map, resolution is exact-match, rules are strictly ordered. Ambiguity can arise only from a defective catalog (duplicate identifiers, two canonical versions, multiple normalizers for one pair), and every such condition is a boot-gate failure.

---

## 7. Failure Taxonomy

A machine-readable code discriminator is carried on the existing `SchemaNegotiationError`. **No new application error type is introduced**, and the error's position in the `KnowledgeGraphApplicationError` hierarchy is unchanged. HTTP mapping is out of scope and not designed here.

| Code | Meaning | Detected | Retryable | Class |
|---|---|---|---|---|
| `MALFORMED_SCHEMA` | Not a well-formed fully-qualified identifier (alias, partial pin, range, wildcard) | Negotiation | No | Client contract violation |
| `UNKNOWN_SCHEMA` | Identifier absent from the catalog | Negotiation | No | Client contract violation |
| `RETIRED_SCHEMA` | Retired tombstone; never reactivated on request (ADR-032 §2.4) | Negotiation | No | Client contract violation |
| `INCOMPATIBLE_SCHEMA` | Catalog classification is Migration required or Incompatible | Negotiation | No | Client contract violation |
| `ADAPTER_FAILURE` | A normalizer raised, or produced values violating the closed-field-domain or no-authority invariants | Normalization | No | **Server defect — alert** |
| `NEGOTIATION_UNCONFIGURED` | The explicitly-enabled non-production fail-closed placeholder was invoked | Negotiation | No | Operator/configuration signal |

**Codes are stable identifiers**, not human-readable text; message text may change freely without breaking a consumer.

### 7.1 Failure modes with no runtime code — eliminated by construction

| Condition | Where it surfaces instead |
|---|---|
| Missing normalizer | Boot gate → startup failure |
| Ambiguous normalizer selection | Boot gate → startup failure |
| Ambiguous negotiation | Boot gate → startup failure |
| Normalizer declaring a prohibited field write | Boot gate → startup failure |
| Catalog absent / malformed / no canonical version | Startup failure (§8) |
| **Registry unavailable** | **Does not exist.** D1-B + D7 make the registry in-process and immutable after boot; there is no runtime dependency to be unavailable. |

**Retry doctrine.** No negotiation failure is retryable. Each is either a client contract violation or a server defect, and neither changes on retry.

**`ADAPTER_FAILURE` is the only server-defect code**, and it is deliberately distinguished so it can be alerted separately from client-caused rejections. It occurs strictly before command construction: no command exists, no transaction is opened, no ledger entry is written, no graph read occurs.

---

## 8. Startup and Environment Behaviour

Revision 1's conditional injection was ambiguous about whether an absent catalog was tolerable. Revision 2 is explicit.

| Environment | Catalog present and valid | Catalog missing or invalid |
|---|---|---|
| **Production** | Registry-backed negotiator injected; readiness reported | **Startup / readiness failure.** The process does not become ready and receives no traffic. No placeholder, no fallback, no exception. |
| **Development / Test** | Registry-backed negotiator injected | Startup failure **by default**. A fail-closed placeholder may be injected **only when explicitly enabled** by an opt-in setting. |

**Rules governing the placeholder:**

1. It is **fail-closed** — it rejects every negotiation with `NEGOTIATION_UNCONFIGURED`. It is never permissive.
2. It requires **explicit enablement**. It is never selected automatically by absence of configuration.
3. Enabling it is **prohibited in production** and is a startup failure there, regardless of the setting.
4. Its use is visible in health output and metrics; a service running on the placeholder is never silently indistinguishable from a correctly configured one.

**There is no automatic permissive fallback anywhere in this design, in any environment.**

The existing `_UnconfiguredSchemaNegotiator` becomes exactly this explicitly-enabled placeholder. Its fail-closed behaviour — the reason the current outage is safe rather than dangerous — is preserved deliberately.

---

## 9. Configuration Model

Configuration modelling only; no format specified, no artifact authored.

**Immutable — fixed at deployment, never runtime-mutable:** the known-version set and each version's state; deprecation and retirement instants; the canonical execution schema version; absolute compatibility classifications; normalization requirements and the normalizer set; retirement tombstones; the catalog generation identifier.

**Runtime — environment-varying, but fixed at process start:** the catalog artifact location; the explicit non-production placeholder enablement (§8); observability verbosity; deprecation-signal thresholds.

**Prohibited configuration** — each would defeat a decision above:

- A **default schema version** for an absent header (P4; an implicit-downgrade vector).
- A **permissive mode** accepting unknown versions (P4).
- **Per-request** selection of normalizers or compatibility class (P3).
- Runtime **mutation** of any immutable value (ADR-032 §2.1, P6).
- **Any exposure of Draft schemas** to runtime negotiation (D4).

---

## 10. Operational Concerns

### 10.1 Metrics

Negotiation outcome counter, dimensioned by requested identifier, outcome, failure code, and catalog generation. Deprecated-version usage counter by version and client identity class. Normalization application counter and latency histogram by version pair — satisfying ADR-032 §2.5's mandated Translation Latency metric. Catalog generation gauge, for fleet-skew detection. `ADAPTER_FAILURE` counter, alerted separately as a server-defect signal.

### 10.2 Logging

Structured, at the negotiation and normalization boundaries only: requested identifier, accepted contract version, canonical execution schema, outcome, failure code, compatibility classification, normalizer pair if applied, catalog generation, correlation identifier. Deprecation emits a distinct non-error event so it is not lost in error-rate noise. **No payload content is logged** — negotiation is a metadata decision and must not become an exfiltration surface.

### 10.3 Audit — corrected scope *(RT-1)*

**Version 1 makes no durable audit claim.**

Confirmed by direct inspection: `mutation_ledger` contains no column for the negotiated schema version. `command_schema_version` is the internal command-envelope version (ADR-030 Rev 4 §5.1, initial value `1`) — a different concept that ADR-033 neither uses nor changes. The accepted contract version currently terminates at an HTTP response header and is not persisted anywhere.

Therefore, in Version 1:

- The **accepted contract version** and the **catalog generation** are exposed only through **health endpoints, metrics, and structured logs**.
- Neither is written to the mutation ledger, the idempotency index, or any other durable store.
- ADR-032 §2.4's requirement that "the effective schema version is included in all audit records" is **not yet satisfied by this ADR** and is recorded as an open gap (§14, OG-1), not claimed as delivered.

**Durable ledger recording requires a separate ADR or an ADR-030 revision**, because it would add a persisted column, change the ledger's immutable record shape, and require a migration — all squarely within ADR-030's authority, not ADR-033's.

### 10.4 Health and discovery

**Readiness** is gated on successful catalog load and a passed boot gate — the mechanism that converts a configuration defect into a failed deployment rather than an outage. Health output reports the catalog generation, the canonical execution schema, and whether the placeholder is active. **Liveness** is unaffected; the registry cannot fail after boot.

A **discovery surface** publishes the supported version set, each version's state, retirement instants, and the recommended current version. This is where `latest` legitimately lives (D3), and it is the primary mitigation for D5's diagnostic loss.

---

## 11. Closed Review Decisions

The Board's decisions are incorporated as normative:

| Question | Decision | Where normative |
|---|---|---|
| Normalizer approval governance | **Normalizers follow the same governance process as schema changes** — ADR-032 §2.5 three-party approval (Ontology Architect + Security Architect + AI Governance Lead). A normalizer is part of the compatibility contract, not implementation detail. | D6, §13 R5 |
| Compatibility classification representation | **Absolute within the catalog.** Classifications are stored as resolved values, not relative offsets computed at load. A reviewer sees the actual classification rather than computing it. This also reinforces D5. | D2, D5 |
| Query Engine adoption | **Only after the mutation path is proven in production.** Directly determines D1's reversal to service-local. | D1, §13 Phase 4 |

**Remaining deferred:** schema families (OQ-1) and cross-service schema propagation (OQ-2), §14.
**Withdrawn as moot:** Revision 1's question on Experimental versions in the ledger — D4 removes Experimental from runtime.

---

## 12. Security Analysis

| Threat | Control |
|---|---|
| **Downgrade attack** (request an older version for weaker validation) | Normalization may not write any classification-, owner-, tenant-, or principal-bearing value (§4.1, P5), enforced at boot. Authorization and classification enforcement occur downstream and are unchanged. Older versions remain subject to identical enforcement (ADR-032 §2.4). |
| **Silent downgrade via response semantics** | Strengthened in Rev 2: the header always reports the client's own requested version on success (§6.2). A client's contract is either honoured or the request is rejected — there is no success path that quietly substitutes a different contract. |
| **Downgrade via absent header** | No default version is permitted (§9). The header is required at transport. |
| **Version probing** | Supported versions are a public contract (ADR-032 §1); the discovery surface removes the incentive. `UNKNOWN_SCHEMA` and `RETIRED_SCHEMA` are deliberately distinguishable because both are public facts. |
| **Probing for tenant-specific schemas** (future) | Recorded constraint on any future overlay ADR: errors must not distinguish "unknown to the platform" from "not enabled for your tenant." |
| **Denial of service via negotiation** | D3 + D5 make negotiation a constant-time lookup on an unparsed identifier: no regex, no ordering, no range arithmetic, no I/O. Attacker-controlled input cannot increase cost. |
| **Denial of service via normalization** | Normalizers are pure, total, single-step, non-I/O, and closed over the DTO field domain; latency is metered per pair. |
| **Catalog tampering** | Version-controlled artifact under CODEOWNERS with three-party approval; read-only at runtime, immutable in memory. |
| **Audit repudiation** | Partially addressed. D3 + D7 make the accepted contract reproducible, but §10.3 confirms it is **not durably recorded** in v1, so non-repudiation is not yet achieved. Tracked as OG-1. |

---

## 13. Migration Strategy

Five phases. At every boundary the system is either fail-closed or correct; no phase is permissive-and-wrong.

| Phase | Change | Runtime effect | Rollback |
|---|---|---|---|
| **0** | Author the catalog artifact and governance (CODEOWNERS, three-party approval covering **both** schema versions and normalizers, per §11). Not loaded. | None. Mutations still fail closed. | Delete artifact |
| **1** | Introduce the service-local registry, loader, validator, boot gate, and the `CompatibilityAdapterRegistry` port. Exercised only in tests; not wired into composition. | None. Mutations still fail closed. | Remove component |
| **2** | Composition root loads the catalog, runs the boot gate, injects the registry-backed negotiator and normalizer registry, and extends `MutationRequestPreparer` with the normalization step. Startup semantics per §8 take effect. | Mutations begin succeeding where a catalog is configured. Environments without one now **fail to start** rather than fail per-request. | Deployment rollback |
| **3** | Ship a **single-version catalog** (canonical only, empty normalizer set). | The full negotiation path runs in production with normalization always identity — normalization risk is zero. Boot gate, readiness gating, and observability are validated under real traffic. | Deployment rollback |
| **4** | On first genuine second version, add it plus its normalizer, gated by the boot gate. **Query Engine adoption may begin only after this phase is stable** (§11). | Normalization path activates. | Deployment rollback (atomic under D7) |

**Why Phase 3 exists.** It separates "does negotiation work in production?" from "does normalization work?", which would otherwise land in one deployment.

**Note on Phase 2's operational change.** Environments that currently start and fail per-request will, after Phase 2, fail to start without a catalog. This is the intended P1 behaviour and must be communicated to operators before the phase ships; it is the one phase with a non-obvious operational consequence.

---

## 14. Acceptance Criteria

**Structural**

1. `emg_knowledge_graph` imports nothing from `emg_knowledge_graph_infrastructure` or the catalog implementation.
2. `SchemaNegotiator`, `SchemaNegotiationRequest`, `SchemaNegotiationResult` are unchanged in shape.
3. `KnowledgeGraphApplication`, mutation commands, DTOs, `MutationExecutionResult`, `MutationResponse`, HTTP routes and headers, and atomic mutation execution are unchanged.
4. `CompatibilityAdapterRegistry` is a new application port; `MutationRequestPreparer`'s extension is the only other internal contract change (§2.1).
5. `PreparedMutation` is unchanged, including `effective_schema_version`.
6. Existing dependency-governance checks pass with no manifest exception.

**Pipeline**

7. The pipeline order in §4 holds without variation: DTO → negotiation → normalization → canonical values → construction → validation → execution.
8. Normalization consumes and produces Request DTOs only; no normalizer observes or produces a command.
9. Normalization is the identity transformation for Strict and Backward classifications.
10. No normalizer output differs from its input in any classification-, owner-, tenant-, or principal-bearing value.

**Behavioural**

11. Every row of §6.3 produces exactly the stated outcome and code.
12. On every success, `Effective-Schema-Version` equals the requested version — including when normalization ran.
13. No negotiation or normalization failure constructs a command, opens a transaction, writes a ledger entry, or reads the graph.
14. A Deprecated version succeeds and emits a deprecation signal.
15. No code path performs ordering, comparison, or structural interpretation of version identifiers beyond well-formedness (D5).
16. Identical request + identical catalog generation ⇒ identical outcome.
17. No catalog state other than Published, Deprecated, or Retired is negotiable.

**Replay verification** *(replaces Revision 1's retracted assertion, RT-2)*

18. **Verified against the actual replay implementation** (`atomic_mutation.py` and ADR-030 Rev 4 §8): confirm that the negotiated schema version is not an input to fingerprint computation, the idempotency claim comparison, or replay-result reconstruction; and that introducing negotiation changes no replay outcome for any command. If verification shows the negotiated version *does* influence replay, ADR-033 must return to the Board before Phase 2.

**Boot and startup**

19. Absent, malformed, canonical-less, duplicate-identifier, or ambiguous-normalizer catalogs all prevent readiness.
20. A normalization-required entry with zero or multiple normalizers prevents readiness.
21. A normalizer declaring a prohibited field write prevents readiness.
22. In production, missing or invalid catalog is a startup/readiness failure with no placeholder path.
23. The placeholder is injected only when explicitly enabled, is fail-closed, is prohibited in production, and is visible in health output.
24. No configuration combination in any environment yields permissive behaviour.

**Security and observability**

25. No configuration path yields a default schema version.
26. Negotiation performs no I/O and no unbounded parsing.
27. Every negotiation failure carries a stable machine-readable code from §7.
28. Catalog generation appears in health output, metrics, and structured logs — and in no durable store (§10.3).

---

## 15. Open Gaps and Deferred Questions

**Open gap requiring a future decision**

- **OG-1 — Durable recording of the accepted schema version.** ADR-032 §2.4 requires the effective version in all audit records. Version 1 does not satisfy this: the value is observability-only (§10.3). Closing it requires a persisted ledger column and migration, which is ADR-030's authority. **A separate ADR or ADR-030 revision is required.** Recorded as an explicit, disclosed gap rather than a claimed capability.

**Deferred by Board decision**

- **OQ-1 — Schema families.** `SchemaNegotiationRequest` carries a single identifier. Whether a family dimension can be namespaced into it or requires a port change is deferred. D5's removal of structural inference makes this cheaper to resolve later, since no runtime code depends on identifier structure.
- **OQ-2 — Cross-service schema propagation.** Whether a mutation's accepted contract propagates to downstream work or each service negotiates independently is deferred. Noted so it is not decided by accident.

---

# 2. Response Matrix

| # | Review item | Resolution | Location |
|---|---|---|---|
| **1** | Acknowledge narrow internal application-contract changes; stop claiming byte-for-byte preservation | **Resolved.** §2.1 explicitly names three internal contract changes: the new `CompatibilityAdapterRegistry` port, the `MutationRequestPreparer` extension (behaviour + constructor signature), and the `SchemaNegotiationError` code discriminator. §2.2 lists what genuinely remains unchanged. The Revision 1 claim is withdrawn. | §2 |
| **2** | Resolve adapter ordering contradiction; one pipeline; define what normalization consumes and produces | **Resolved.** §4 states the single pipeline and it is used without variation in every diagram, table, and rule. §4.1 defines normalization as consuming (validated Request DTO + NegotiationOutcome) and producing Canonical Request Values within the same DTO family. Normalizers are DTO-to-DTO only and **never** command transformers; the contradictory Revision 1 §5.5 framing is removed. Terminology standardized on "normalizer." | §4, §4.1 |
| **3** | Clarify `Effective-Schema-Version`; separate client contract from canonical internal execution schema; keep the header; define it | **Resolved.** §6.1 defines the two concepts in a comparison table. §6.2 states normatively that the header carries the **Accepted Schema Contract** and always equals the client's requested version on success, never the Canonical Execution Schema. Revision 1's canonical-on-normalization behaviour is removed as a latent silent-downgrade signal. Header retained; naming tension disclosed. | §6.1, §6.2 |
| **4** | Retain exact-version; remove the ADR-030-forces-it claim; rejustify on four grounds; make replay an acceptance criterion | **Resolved.** RT-2 retracts the claim with the evidence that refutes it (replay keys on `command_fingerprint` + `command_schema_version`, not the negotiated version). D3 rejustifies on deterministic execution, stable client contracts, audit clarity, and prevention of silent adoption. Replay becomes **AC-18**, requiring verification against `atomic_mutation.py` and ADR-030 §8, with an explicit return-to-Board trigger. | RT-2, D3, AC-18 |
| **5** | Remove Experimental/Draft from Version 1 runtime | **Resolved.** D4 defines exactly three negotiable-catalog states: Published, Deprecated, Retired. Draft remains entirely outside runtime negotiation; the environment-conditional switch is removed. §9 lists Draft exposure as prohibited configuration; AC-17 enforces it. Revision 1's related open question is withdrawn as moot. | D4, §9, AC-17 |
| **6** | Do not claim durable audit for catalog generation; limit to health, metrics, logs; defer durable recording | **Resolved.** RT-1 retracts the claim with the evidence (`mutation_ledger` has no such column; `command_schema_version` is a different concept per ADR-030 §5.1). §10.3 limits both the accepted version and catalog generation to health, metrics, and structured logs. ADR-032 §2.4's audit requirement is recorded as unmet in **OG-1**, requiring a separate ADR or ADR-030 revision. AC-28 enforces the boundary. | RT-1, §10.3, OG-1 |
| **7** | Resolve startup behaviour: production fails; dev/test placeholder only when explicitly enabled; no automatic permissive fallback | **Resolved.** §8 gives an explicit environment matrix and four governing rules: placeholder is fail-closed, requires explicit enablement, is prohibited in production, and is visible in health. Revision 1's ambiguous "conditional injection" is replaced. AC-22/23/24 enforce it. | §8 |
| **8** | Reassess shared-library placement; recommend service-local unless a second consumer is proven | **Resolved — decision reversed.** D1 selects service-local infrastructure. The reversal is grounded in evidence (`SchemaNegotiator` has no consumer outside the mutation path) and in the Board's decision that the Query Engine adopts only after the mutation path is proven. Ports are preserved so extraction is a later mechanical refactor; the extraction trigger is recorded. | D1 |
| **9** | Remove runtime semantic-version ordering; catalog is sole authority; Unknown stays Unknown; no inferred Future Version | **Resolved.** New principle **P7** and new decision **D5**. The "Future version" rule is deleted from §6; §6.3 rows 7 and 8 are deliberately identical, both `UNKNOWN_SCHEMA`. The resulting diagnostic loss is disclosed and mitigated via discovery surface and metrics rather than hidden. AC-15 enforces the prohibition. | P7, D5, §6, AC-15 |
| **10** | Machine-readable failure taxonomy; preserve the application error boundary; no HTTP mapping | **Resolved.** §7 defines six stable codes: the five specified plus `NEGOTIATION_UNCONFIGURED` for the explicitly-enabled placeholder (§8), which is a distinct operator-facing condition. Carried as a discriminator on the existing `SchemaNegotiationError`; no new error type; hierarchy position unchanged. `ADAPTER_FAILURE` is separated as the sole server-defect code. No HTTP mapping is designed. | §7, §2.1 |
| **RD-1** | Close: normalizer approval follows schema governance | **Closed and normative.** ADR-032 §2.5 three-party approval extended to normalizers; embedded in Migration Phase 0. | §11, §13 |
| **RD-2** | Close: compatibility classification absolute in catalog | **Closed and normative.** Reinforces D5 by removing load-time computation. | §11, D2, D5 |
| **RD-3** | Close: Query Engine adopts after mutation path proven | **Closed and normative.** Directly drives D1's reversal and gates Phase 4. | §11, D1, §13 |
| **RD-4** | Keep deferred: schema families | **Deferred as OQ-1**, with the note that D5 makes it cheaper to resolve later. | OQ-1 |
| **RD-5** | Keep deferred: cross-service propagation | **Deferred as OQ-2.** | OQ-2 |

---

# 3. Consistency Verification

### Against ADR-027 Revision 5 (Accepted — HTTP Transport Contract, Stage 4 Phase 4A)

| ADR-027 Rev 5 requirement | Source | Revision 2 status |
|---|---|---|
| "Schema negotiation follows ADR-032 before command construction." | §16, line 432 | **Consistent.** §4's pipeline places negotiation and normalization strictly before command construction. |
| `Preferred-Schema-Version` is required and supplied to the negotiator before command construction. | lines 539–540 | **Consistent.** Header contract unchanged; absent header remains a transport rejection (§6 rule 1). |
| "Handlers contain no authorization decision, schema-negotiation algorithm…" | line 591 | **Consistent.** The algorithm lives in service-local infrastructure behind an application port; handlers are unchanged. |
| "The API layer negotiates the schema version before any command construction." | §1073 | **Consistent.** Negotiation remains an API-layer concern within `MutationRequestPreparer`. |
| Authorization preflight before `GraphStore.transaction()`; `IResourceMetadataReader`; `AtomicMutationExecutionPort`; routers never touch `GraphStore`. | §16, line 432 | **Unaffected.** ADR-033 terminates before command construction and touches none of these. |
| Public response follows ADR-030 Rev 4. | §16, line 432 | **Consistent.** `MutationResponse` unchanged (AC-3). |

**No ADR-027 Rev 5 decision is reopened, contradicted, or superseded.**

### Against ADR-030 Revision 4 (Mutation Ledger & Atomic Idempotency)

| ADR-030 Rev 4 element | Source | Revision 2 status |
|---|---|---|
| `command_schema_version` = "the semantic command-envelope schema stored by this mutation. Initial value: 1." | §5.1, line 197 | **Distinct concept, explicitly separated.** RT-1 and §10.3 state this is not the negotiated ontology version. ADR-033 neither reads nor writes it. |
| Ledger immutability; append-only constraints; no new columns without migration. | §4.4, §5.1 | **Respected.** ADR-033 adds no column and requires no migration. OG-1 defers durable recording to ADR-030's authority. |
| Fingerprint contract; normalization rules; version lookup sequence. | §6.1–6.4 | **Untouched.** The negotiated version is not a fingerprint input. AC-18 requires this to be verified, not assumed. |
| Replay semantics: lookup, replay response, mismatch, failed mutation. | §8.1–8.4 | **Unaffected.** Negotiation fails before any command exists, so no replay record is created. Revision 1's contrary claim is retracted (RT-2). |
| Atomic commit and concurrency; Mutation Unit of Work; commit invariant. | §7.1–7.3 | **Unaffected.** ADR-033 terminates before the transaction boundary. |
| Integration boundaries: GraphStore, Policy Engine/PEP, application service. | §10.1–10.3 | **Unaffected.** No boundary is crossed or redefined. |

**No ADR-030 Rev 4 decision is reopened.** OG-1 is registered as needing ADR-030's authority rather than being taken unilaterally.

### Against ADR-032 (Knowledge Graph Schema Versioning & Evolution)

| ADR-032 requirement | Source | Revision 2 status |
|---|---|---|
| Published versions are immutable. | §2.1 | **Enforced.** D2's artifact is read-only at runtime; D4 removes Experimental, whose mutability was in tension with this. |
| Lifecycle Draft → Published → Deprecated → Sunset. | §2.1 | **Consistent, narrowed.** D4 maps Sunset ≡ Retired and confines the runtime catalog to Published/Deprecated/Retired. Draft remains a governance-only state — a narrowing of runtime exposure, not a redefinition of the lifecycle. |
| Server publishes its authoritative supported list; clients express a preference; server validates against policy. | §2.3 | **Consistent.** Discovery surface (§10.4) publishes; §6 validates against the catalog. |
| Unsupported/retired/incompatible requests rejected deterministically, before execution. | §2.3, §2.4 | **Consistent.** §6 is deterministic and total; AC-13 requires failure before any command, transaction, ledger entry, or graph read. |
| Compatibility matrix: N, N−1, N−2 adapter, N−3 migration, N−X incompatible, Retired. | §2.4 | **Adopted as classification, stored absolutely** (RD-2). D5 removes runtime derivation of the relative offsets; the classification itself is unchanged. |
| Retired versions are not reactivated because a client requests them. | §2.4 | **Enforced.** Permanent tombstones; `RETIRED_SCHEMA`. |
| Adapters cannot weaken security or classification rules. | §2.4 | **Enforced structurally.** §4.1's no-authority rule, boot-checked, with AC-10 and AC-21. |
| Breaking changes cannot be silently exposed to incompatible consumers. | §2.4 | **Strengthened in Rev 2.** §6.2 guarantees a success always confirms the client's own requested contract; no success path substitutes a different one. |
| **The effective schema version is included in all audit records.** | §2.4 | **NOT SATISFIED in Version 1 — disclosed, not claimed.** §10.3 and OG-1. This is the one ADR-032 requirement Revision 2 leaves open, and it is stated as a gap rather than asserted as delivered (correcting RT-1). |
| Multi-party approval for schema changes. | §2.5 | **Consistent and extended.** RD-1 applies the same governance to normalizers; embedded in Phase 0. |
| Translation Latency metric. | §2.5 | **Satisfied.** §10.1 normalization latency histogram by version pair. |
| Automated deprecation notifications (future work). | §6 | **Enabled.** §10.1's deprecated-usage counter with retirement instants is the required input. |

**Assessment:** Revision 2 is consistent with ADR-032 on every point except the audit-record requirement, which is now honestly disclosed as unmet rather than falsely claimed.

---

# 4. Final Architecture Board Recommendation

## **ACCEPT**, with two binding conditions.

### Justification

**All ten required changes are resolved in the document, not merely acknowledged.** Each is traceable to a specific section, and eight are additionally enforced by a numbered acceptance criterion, so conformance is verifiable at implementation review rather than by reading intent.

**Two Revision 1 claims were factually wrong and are retracted with the evidence that refutes them.** RT-1 (the ledger does not store the negotiated version) and RT-2 (replay is not keyed on it) were both verifiable against the repository, and both were asserted in Revision 1 without verification. The review was correct to flag them. Their retraction materially changes the document: the audit claim becomes a disclosed gap (OG-1), and D3 now rests on architectural grounds that survive scrutiny rather than on a false dependency.

**Three changes improved the architecture beyond compliance:**

- **Item 2** eliminated a genuine ambiguity that would have produced two incompatible implementations. The single pipeline, with normalization defined as strictly DTO-to-DTO, also strengthened the closed-field-domain rule into the operative boundary between adaptable and breaking.
- **Item 3** exposed that Revision 1's canonical-on-normalization header was a silent-downgrade signal in disguise. Under Revision 2 a success always confirms the client's own contract — a security improvement, not only a clarity one (§12).
- **Item 9** removed a competing authority. Revision 1 had the catalog and the identifier's structure both determining compatibility; only one can be authoritative. The cost — losing the distinct future-version diagnostic — is real and disclosed rather than argued away.

**Item 8's reversal is the correct call and the Board should note why Revision 1 got it wrong:** it argued from `GraphStore` duplication precedent, but that precedent applies when two consumers exist. Predicting a second consumer is not evidence of one.

### Binding conditions

**C1 — AC-18 must be discharged before Migration Phase 2.** Replay compatibility is now an assertion requiring verification against `atomic_mutation.py` and ADR-030 Rev 4 §8, not a claim. If verification shows the negotiated version influences fingerprinting, the idempotency claim, or replay reconstruction, ADR-033 returns to the Board. This condition exists specifically because Revision 1 asserted this relationship incorrectly.

**C2 — OG-1 must be assigned an owner and a target ADR at acceptance.** ADR-032 §2.4 requires the effective version in audit records, and Version 1 does not deliver it. Accepting ADR-033 without assigning OG-1 would leave an accepted-ADR requirement unowned indefinitely. ADR-033 correctly declines to resolve it unilaterally, since it falls within ADR-030's authority — but declining is not the same as assigning.

### Residual risks the Board accepts

- **R5 — normalizer accretion into shadow business logic.** §4.1 constrains shape, not judgment. RD-1's governance requirement is the primary control, and it depends on sustained review discipline. The Board should name a normalizer-review owner.
- **D5's diagnostic loss.** Clients deployed ahead of their server receive `UNKNOWN_SCHEMA` with no distinct signal. Mitigated operationally, not eliminated.
- **D3's client friction.** Exact pinning imposes continuous cost on every client. Now justified on four grounds rather than one false one, but it remains the decision most likely to attract future pressure to relax.

---

## Self-Assessment — Revision 2

| Dimension | Rev 1 | **Rev 2** | Change |
|---|---|---|---|
| **Consistency** | 92 | **95** | The pipeline contradiction and the two schema-version conflations are resolved; §3 verifies against all three ADRs line-by-line. Remaining deduction: ADR-032 §2.4's audit requirement is unmet, though now disclosed. |
| **Extensibility** | 78 | **80** | D5's removal of structural inference makes schema families cheaper to add later. Deduction: D1's reversal to service-local defers the extraction cost — correctly, but the cost is deferred, not removed. |
| **Maintainability** | 88 | **90** | One unambiguous pipeline and one authority for compatibility remove the two most likely sources of divergent implementation. Deduction: R5 persists. |
| **Operational readiness** | 94 | **93** | §8's explicit startup matrix and §7's stable code taxonomy are improvements; the small decrease reflects honesty rather than regression — Revision 1 scored partly on an audit capability (RT-1) that does not exist. |
| **Future evolution** | 76 | **78** | Three questions closed as normative; two deferred with a stated constraint; OG-1 registered with the correct owning ADR. Deduction: OQ-1 and OQ-2 remain genuinely open. |
| **Overall** | 87 | **91** | The document is now correct where it was previously confident. Its strength remains eliminating an entire failure class by construction; its weakness remains that normalizer discipline is enforced by governance rather than by structure. |

**Where Revision 2 is most likely to be wrong:** D3's exact-pinning requirement. Its four justifications are architecturally sound but none is *forcing* — a Board that weighs client friction more heavily could reasonably reach a different conclusion. Everything else in the document survives that change; D3 is the only decision whose reversal would not cascade.

---
