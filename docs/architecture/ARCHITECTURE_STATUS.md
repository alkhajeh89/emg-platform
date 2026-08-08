# EMG™ Architecture Status

## Project Status

Architecture Phase: Frozen

Engineering Phase: Active

Current Branch: See repository branch and release records; this document is not the authoritative source for the active Git branch.

Current Delivery Focus: Studio Phase 2B security enablement — ADR-038 accepted; implementation remains gated by mandatory non-production delegation capability verification.

## Delivery Track Taxonomy

The following delivery tracks are distinct and must not be inferred to advance
one another:

- **ADR-027 Revision 5 delivery track.** Stage 4 is complete. Phase 4A, the
  HTTP mutation transport and conformance phase, completed at PR #37 (merge
  commit `aefc82c`). Phase 4B, mutation-path observability emission, was
  implemented at `c6c28bb` and merged through PR #45 at `6536b73`; it emits
  `mutation_requests_total`, `mutation_latency_seconds`,
  `idempotency_hits_total`, `authorization_denials_total`, and safe structured
  logs without adding a route, command, or DTO change. Phases 4C and 4D are
  closed as not required. Phase 4E governance and conformance closure is
  complete. The five-route transport surface remains unchanged and
  authoritative. ADR-027 owns metric **emission**; ADR-015 / FEAT-12-3 owns
  collection, storage, dashboards, tracing, and alerting. No UI is authorized
  in Stage 4. ADR-027 **Stage 5** deployment documentation is complete at
  `docs/specifications/ADR-027/ADR-027_STAGE5_DEPLOYMENT_AND_ROLLOUT.md`; it
  documents role, policy-rule, and claim provisioning requirements only and
  claims no production readiness. Production rollout prerequisites remain open.
- **ADR-033 Revision 2 schema track.** Phase 3 is complete at commit `5288392`.
  ADR-033 Phase 4 is the future schema-registry phase for the first genuine
  second schema version and its production normalizer; it has not started. It
  is not ADR-027 Phase 4B. The supported-schema discovery surface remains
  governance-blocked pending a ratified URI, authentication model, and response
  DTO.
- **Production-readiness track.** Security, operations, deployment, resilience,
  accreditation, and release-readiness work is tracked independently.
  Completion of a production-readiness item does not by itself advance
  ADR-027 or ADR-033, and Phase 4A completion does not claim platform-wide
  production readiness.
- **Future UI/product-delivery track.** Any user interface, self-service
  recovery portal, or other frontend surface is separate future product work.
  Neither ADR-027 Phase 4A nor ADR-033 Phase 3 defines or authorizes UI scope.

---

## Approved Architecture

Architecture Baseline v1.0

Status: Frozen — changes require a new ADR.

---

## Modules — Architecture Approval Status

All ten modules are **architecture-approved** (design frozen in Architecture
Baseline v1.0, §Module Summary). Architecture approval means the module's
design has been reviewed and frozen by the Architecture Board — it does
**not** mean the module has been engineered yet. See "Modules — Engineering
Status" below for what actually exists in this repository.

| Module | Name | Architecture Status |
| --- | --- | --- |
| Module 1 | Repository Structure | Approved — Frozen |
| Module 2 | Development Environment | Approved — Frozen |
| Module 3 | Shared Libraries | Approved — Frozen |
| Module 4 | Identity & Authentication | Approved — Frozen |
| Module 5 | Enterprise Authorization & Policy Platform | Approved — Frozen |
| Module 6 | Enterprise Audit, Provenance & Digital Evidence Platform | Approved — Frozen |
| Module 7 | Enterprise Knowledge Graph Platform | Approved — Frozen |
| Module 8 | Enterprise Search, GraphRAG & Knowledge Retrieval Platform | Approved — Frozen |
| Module 9 | Enterprise AI Orchestration & Agent Platform | Approved — Frozen |
| Module 10 | Enterprise Decision Intelligence Platform | Approved — Frozen |

---

## Modules — Engineering Status

This table reflects what is actually implemented in this repository, verified
against `services/*/service.yaml` and the test suite — not aspirational
status.

| Module | Engineering Status | Notes |
| --- | --- | --- |
| Modules 1–3 (Foundation) | Complete | Sprint 1 — monorepo, shared library scaffolding, local dev environment, CI skeleton |
| Module 4 (Identity & Authentication) | Implemented through Sprint 3 | FEAT-02-1, FEAT-02-2 (Sprint 2); FEAT-02-3, FEAT-02-4 (Sprint 3) |
| Module 5 (Authorization & Policy) | Authorization baseline complete through FEAT-03-4; **first live enforcement adopter delivered (ADR-025, 2026-07-27)** | FEAT-03-1, FEAT-03-2 (Sprint 4); FEAT-03-3 (RBAC Baseline Roles), FEAT-03-4 (Authorization Testing Harness) (Sprint 5). `services/authz` remains scaffolded (library-first approach; see Sprint 4 and Sprint 5 design docs). FEAT-04-1 (Audit Event Pipeline), grouped with FEAT-03-3/03-4 in the Backlog's Sprint 5 row, is rescheduled to the next Audit sprint (see Sprint 5 scope note below). ADR-025 (Knowledge Graph Integration Closure, Group C) makes `services/knowledge-graph` the first service to actually enforce (not just introspect) an authorization decision using this module's PEP/`emg-policy-engine` stack — see Module 7 row and the ADR-025 entry in the ADRs table below. |
| Module 6 (Audit) | Complete through FEAT-04-4 — **EPIC-04 complete (merged)** | FEAT-04-1 (Sprint 6, PR #6, `1fe6bc7`); FEAT-04-2 + FEAT-04-3 (Sprint 7, PR #7); FEAT-04-4 (Audit Query & Reporting Interface — Sprint 8, **merged PR #8, merge commit `79eaae6`**) adds classification-aware audit + custody queries, opaque-cursor keyset pagination, and JSON/CSV report export (backend only, `svc-audit`, no new role/ADR). **EPIC-04 (Audit Platform) is complete (FEAT-04-1 → FEAT-04-4)**; the EPIC-05 (Module 7) dependency gate is unblocked. SRS-2 adds verified-tenant confinement and PEP-backed classification authorization to event lookup, listing, pagination, and export. |
| Module 7 (Knowledge Graph) | In Progress — domain libraries complete; query API and ADR-027 Revision 5 Stage 4 complete (PR #45, `6536b73`); ADR-033 Revision 2 complete through Phase 3 | FEAT-05-1 through FEAT-05-5 are implemented as libraries. `services/knowledge-graph` exposes the ADR-022/023/024 query surface with ADR-025/026 authorization and classification enforcement, plus exactly the five mutation routes approved by ADR-027 Revision 5. Phase 4A completed at PR #37 (`aefc82c`). Phase 4B observability emission was implemented at `c6c28bb` and merged through PR #45 (`6536b73`). Phases 4C and 4D are closed as not required, and Phase 4E governance and conformance closure is complete. ADR-027 owns metric emission; ADR-015 / FEAT-12-3 owns collection, storage, dashboards, tracing, and alerting. ADR-029 replacement semantics and ADR-030 atomic mutation ledger are implemented. ADR-033 Revision 2's canonical-only production catalog remains active through Phase 3; its separate Phase 4 has not started, and no second schema version or production normalizer exists. ADR-027 Stage 5 documentation is complete at `docs/specifications/ADR-027/ADR-027_STAGE5_DEPLOYMENT_AND_ROLLOUT.md` and claims no production readiness; Stage 5 production rollout remains open. **Updated 2026-08-03:** the Neo4j serving-projection binding is no longer deferred — `services/knowledge-graph` now composes the lazy Neo4j projection and the bounded PostgreSQL pool with explicit lifecycle ownership (P-01, P-04). |
| Module 8 (Search / GraphRAG / Retrieval) | Scaffolded | `services/retrieval/service.yaml`: `status: scaffolded`. No implementation yet. |
| Module 9 (AI Orchestration) | Scaffolded | `services/ai-orchestration/service.yaml`: `status: scaffolded`. No implementation yet. |
| Module 10 (Decision Intelligence) | Not implemented | ADR-037 is Accepted and defines the Decision domain contract, but this branch contains no Decision ontology model, Decision Query Service, Decision HTTP API, Studio aggregate backend, or Studio frontend. Architecture acceptance does not imply implementation. |

A module's engineering status only advances when this repository proves it —
by committed, tested code — never by this document alone.

---

## Phase 2 — Persistence Binding (Durable Memory Substrate)

**Complete.** `libs/python/emg-persistence` implements the `GraphStore` port
with PostgreSQL as the authoritative revision log and Neo4j as a rebuildable
serving projection (ADR-1/ADR-5), including compare-and-set concurrency, a
transactional outbox, catch-up/read-repair/rebuild, and a PostgreSQL read
fallback when Neo4j is unavailable. Proven in the `persistence` CI job
(PostgreSQL 16 + Neo4j 5 Community); full detail, validation evidence, and
final test counts live in `docs/phases/phase-2/PHASE2_COMPLETION.md`, which
is the authoritative source for Phase 2 status — this entry is a summary
pointer only and is not kept in sync line-by-line with that document.

**Post-Phase-2 hardening (P-01 … P-05), merged 2026-08-02.** Five narrow
changes landed after the Phase 2 completion record was written. They add no
architecture decision and change no ADR:

- **P-01** (`cdbf0ca`, PR #52) — current reads now prefer the Neo4j serving
  projection with read-repair, falling back to PostgreSQL. The authoritative
  head is still read from PostgreSQL first.
- **P-02** (`9d464ed`, `c9ce138`, PR #55) — `EvidenceLedgerRepository` is
  implemented as an internal `emg-persistence` capability under the accepted
  P-02 contract addendum. No ingestion wiring, API, worker, UI, or product
  capability was introduced, and it has no production caller.
- **P-03** (`b99b9af`, PR #50) — migration V006 narrows the runtime role's
  `UPDATE` grants to specific columns.
- **P-04** (`8afadb9`, `78a3919`, PR #51) — lazy bounded PostgreSQL pooling
  with explicit lifecycle ownership at the service boundary.
- **P-05** (`8972aa7`, PR #48) — mutation-dispatch claims are bounded by an
  explicit `max_attempts`.

Current implementation detail now lives in two living documents:
`docs/engineering/persistence-architecture.md` and
`docs/engineering/persistence-operations.md`. Deferred items — the continuous
`ProjectionWorker` daemon (TD-002), the P-02 EL-10 evidence-ledger schema
hardening, and audit dispatch delivery — remain open and are recorded there.

---

## ADRs

Only the following Architecture Decision Records are currently present in
`docs/architecture/`:

| ADR | Title | Status |
| --- | --- | --- |
| ADR-014 | Enterprise Presentation Architecture | Approved — Frozen. **Updated 2026-08-03:** the "approved Enterprise UX Architecture & Design System" this ADR cites existed in the repository only as a stub. `docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md` (DS-001, Accepted 2026-08-03) now supplies that substance and is the canonical design-system authority; `docs/frontend/design-system/` is derived implementation guidance. ADR-014's BFF mandate is corroborated by ADR-036. No ADR-014 decision is altered |
| ADR-015 | Unified Enterprise Observability | Approved — Frozen |
| ADR-016 | Enterprise Ownership Registry | Approved — Frozen |
| ADR-017 | Enterprise Capacity & Scalability Model | Approved — Frozen |
| ADR-018 | Bilingual Enterprise Architecture (Arabic + English) | Accepted — Foundation invariant |
| ADR-019 | AI Orchestration Layer | Proposed |
| ADR-020 | Knowledge Ingestion Layer | Proposed |
| ADR-021 | Enterprise API Strategy | Proposed |
| ADR-022 | Knowledge Graph Revision Build Workflow | **Accepted — ratified 2026-08-03; implemented.** Previously carried `Proposed` while already implemented (Architecture Baseline Review finding MAJ-1). Ratification changed governance metadata only; no architectural decision was altered. `build_revision` remains internal orchestration and is not a production mutation ingress (ADR-022 §5.9) |
| ADR-023 | Knowledge Graph Revision History & Navigation | **Accepted — ratified 2026-08-03; implemented.** Same MAJ-1 correction. `GraphRevisionReader`, `RevisionMetadata`/`HistoricalGraphRevision`, the extended `WriteReceipt`, and the four orchestrator methods are live |
| ADR-024 | Knowledge Graph Query Engine | **Accepted — ratified 2026-08-03; implemented.** Same MAJ-1 correction. Application-layer query engine with seven HTTP query routes, cursor pagination, and fixed safety limits |
| ADR-025 | Knowledge Graph Tenant & Authorization Model | **Accepted — implemented (Group C, 2026-07-27)** |
| ADR-026 (Revision 2) | Knowledge Graph Classification Enforcement Model | **Accepted — fully implemented (Phase 1 + Phase 2, D1–D13, 2026-07-27)** |
| ADR-027 (Revision 5) | Knowledge Graph Mutation API | **Accepted — Stage 4 complete (PR #45, merge commit `6536b73`, 2026-08-01)**: Phase 4A HTTP/API delivery conformance completed at `aefc82c`. Phase 4B mutation-path observability emission was implemented at `c6c28bb` and merged through PR #45 at `6536b73`. Phases 4C and 4D are closed as not required; Phase 4E governance and conformance closure is complete. Exactly five approved HTTP mutation routes remain unchanged and authoritative. ADR-027 owns metric emission; ADR-015 / FEAT-12-3 owns collection, storage, dashboards, tracing, and alerting. Stage 5 deployment documentation is complete at `docs/specifications/ADR-027/ADR-027_STAGE5_DEPLOYMENT_AND_ROLLOUT.md`; it documents role, policy-rule, and claim provisioning requirements only and claims no production readiness. Production rollout prerequisites remain open. |
| ADR-028 | Audit Reconciliation | **Accepted (2026-08-09) — implementation authorized, not implemented.** Establishes a dedicated single-replica RC1 Audit Projector, distinct tenant-scoped Service Principals, tenant-partitioned claims, at-least-once delivery, stable idempotent event identity, bounded durable retry/reschedule, poison/exhausted preservation, crash recovery, graceful shutdown, and backlog observations. No consumer exists yet. Registered 2026-08-03; accepted 2026-08-09 |
| ADR-029 (Revision 2) | Canonical Entity/Relationship Identity, Lifecycle, and Supersession Model | **Accepted — implemented (commit `97b211d`, tag `adr-029-approved-implementation`)** |
| ADR-030 (Revision 4) | Mutation Ledger & Atomic Idempotency | **Accepted — implemented (Stage 3, commit `2dab646`, tag `adr-027-stage-3`)** |
| ADR-032 | Knowledge Graph Schema Versioning & Evolution | **Accepted — mutation-path negotiation implemented; read-path adoption remains governed separately** |
| ADR-033 (Revision 2) | Schema Registry and Negotiation Service | **Accepted — implemented through Phase 3 (commit `5288392`)**: the canonical-only production catalog and mutation-path negotiation are active. ADR-033 Phase 4—the first genuine second schema version and its production normalizer—has not started. Supported-schema discovery remains governance-blocked pending an approved transport contract. |
| ADR-034 | Security State and Service Trust Hardening | **Accepted — implemented by SRS-2 (2026-07-30)** |
| ADR-035 | Human Principal Authentication | **Accepted (2026-08-03) — not implemented.** Discharges the ADR-025 §8.9 reserved extension point. Defines OIDC Authorization Code with PKCE S256 through a confidential BFF client and rejects ROPC for browser use. The existing authorization call site remains unchanged. Requires Keycloak realm configuration because no client currently enables the Authorization Code flow. Downstream delegated human identity is governed separately by ADR-038. This ADR authorizes no code or realm configuration. |
| ADR-036 | Application and BFF Boundary | **Accepted (2026-08-03) — not implemented.** A BFF remains mandatory: the browser can never hold a Service Principal credential without violating the ADR-034 trust model. The BFF is **not** a PEP; service-side authorization and ADR-026 denial shapes remain authoritative. This branch contains no Studio frontend or production BFF. ADR-038 resolves the downstream human-delegation sub-decision formerly recorded in §5, but Phase 2B remains blocked pending ADR-038 capability verification. Closes frontend decision D-F-006. |
| ADR-037 | Decision Domain Model | **Accepted (2026-08-03) — not implemented.** Defines `Decision`, `DecisionOption`, `DecisionRationale`, and `Approval` at the ontology layer, superseding the EPIC-08 deferral at `emg-ontology/references.py:10-12`. Introduces **no new `NodeType`, no new `EdgeType`, and no new mutation route** — the frozen graph vocabulary already carries every required relationship, so Freeze §14 is untouched. Every `Decision` requires at least one `EvidenceRef`. Unblocks four of six frozen Freeze §23 dashboard indicators and completes a fifth |
| ADR-038 | Human Identity Delegation Architecture | **Accepted (2026-08-07) — not implemented.** Selects OAuth 2.0 Token Exchange (RFC 8693) as the authoritative downstream human-identity delegation architecture. Preserves the Human Principal as the authorization subject and the Studio BFF as an independently identifiable Acting Service. Requires a single-audience Delegated Credential, scope reduction, tenant and clearance integrity, bounded lifetime, independent downstream validation, fail-closed behaviour, and complete audit attribution. Resolves ADR-036 §5. Acceptance does not imply implementation; Phase 2B remains blocked until mandatory non-production capability verification and ADR-038 conformance criteria succeed. |


*Implementation Notes (Authorization/Policy):*
- Mutation authorization policy: implemented (commit `78108c9`)
- Writer service role: implemented (commit `6c28b1d`)

ADR-001 through ADR-013 are **not present in this repository** and must not
be described as approved, frozen, or existing until they are actually added
under `docs/architecture/`. ADR-022/023/024 (Knowledge Graph Revision Build
Workflow / Revision History & Navigation / Query Engine) are referenced
elsewhere in this document's Module 7 notes but are not repeated in this
table. The Knowledge Graph and application-security decision chain is recorded here through ADR-038. Engineering implementation status remains tracked separately and SHALL NOT be inferred solely from ADR acceptance.

ADR-019/020/021 accompany `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` and
`IMPLEMENTATION_GAP_ANALYSIS.md` (2026-07-25). They are architecture-only —
no service or library referenced by them has been implemented as a result of
their creation. Their table entries remain additive bookkeeping only. The
Project Status marker above records the merged `develop` baseline through
PR #37 (`aefc82c`). The separate Module/EPIC/Sprint and Phase 0/1/2 numbering
schemes remain unreconciled under D-A-001 and must not be treated as the same
delivery track.

**ADR-025 (2026-07-27) — implemented, not merely accepted.** Unlike
ADR-019/020/021 above, ADR-025 (Knowledge Graph Tenant & Authorization Model)
was both approved and fully implemented the same day: the Knowledge Graph
Query API (`emg_knowledge_graph_api`) now enforces operation-level
authorization on all seven of its routes via the platform's existing
`emg-auth-client`/`emg-policy-engine` stack, fail-closed, default-deny. This
is the platform's **first live enforcement adopter** of that stack —
`services/identity`'s own use of the same libraries (`GET /authz/check`)
remains an introspection endpoint, not an enforcement gate. See
`docs/architecture/EMG_ADR-025_KNOWLEDGE_GRAPH_TENANT_AUTHORIZATION_MODEL.md`
for the full decision record, including two small implementation-time
findings (§18 of that document) and one still-open follow-up (no
registry-based allow-list of recognized Knowledge Graph API client
`client_id`s exists yet, unlike `audit`/`identity`).

**ADR-026 Revision 2 (2026-07-27) — Knowledge Graph Classification
Enforcement, fully implemented (Phase 1 + Phase 2).** Layered on top of
ADR-025's operation-level authorization: the Query API's seven routes now
additionally enforce per-object classification (`UNCLASSIFIED` /
`INTERNAL` / `CONFIDENTIAL` / `SECRET`) via a second call, per returned
object, into the *same* `PolicyEnforcementPoint`/`PolicyEngine` ADR-025
already wired in — never a second authorization mechanism, a ranking
table, or a comparator outside the Policy Engine (Amendment 1 extends
`PolicyRule` with a purely declarative `required_resource_attributes`
field, matched exactly like the existing `required_attributes`). Phase 1
(D1–D6: Policy Engine/auth-client extension, claim provisioning for both
human and machine callers, enumerated policy data) and Phase 2 (D7–D13:
DTO projection, the `emg_knowledge_graph_api.classification` HTTP-layer
adapter, route wiring, deployment docs, the full test suite, boundary
verification, this governance update) are both complete, each delivered
and independently reviewed as a separate batch. Two audited findings
during Phase 2 (a pagination-metadata leak and a denied-history
classification leak) were remediated in the same engagement — see
`docs/architecture/EMG_ADR-026_KNOWLEDGE_GRAPH_CLASSIFICATION_ENFORCEMENT_MODEL.md`
Part F (Phase 1 remediation) and OBS-A-004 in
`EMG_ARCHITECTURE_DECISION_REGISTER.md` (Phase 2 completion record,
including the remediations and the standing rule Appendix ADR-026A now
establishes for any future `required_resource_attributes` reuse).
`emg_knowledge_graph` (the Query Engine/domain layer), `PolicyEngine`, and
`PolicyEnforcementPoint` were not modified for any of this — verified by
an extended dependency-boundary test suite (Group D12) confirming no
principal/authorization concept exists in `emg_knowledge_graph` and no
scripting/ranking capability exists in `emg_policy_engine`.

---

## Engineering Progress

| Sprint | Status |
| --- | --- |
| Sprint 1 | Complete |
| Sprint 2 | Complete |
| Sprint 3 | Complete |
| Sprint 4 | Complete |
| Sprint 5 | Complete (merged) |
| Sprint 6 | Complete (merged — PR #6, `1fe6bc7`) |
| Sprint 7 | Complete (merged — PR #7) (EPIC-04 — FEAT-04-2 + FEAT-04-3) |
| Sprint 8 | Complete (merged — PR #8, `79eaae6`) (EPIC-04 completion — FEAT-04-4 Audit Query & Reporting) |
| Sprint 9 | Complete (merged — PR #9, `2fcbaa9`) (EPIC-05 — FEAT-05-1 Core Ontology, library-first) |
| Sprint 10 | Complete (merged — PR #10, `bf8d460`) (EPIC-05 — FEAT-05-2 Knowledge Ingestion Pipeline, library-first) |
| Sprint 11 | Complete (merged — PR #12, `d27ab59`) (EPIC-05 — FEAT-05-3 Knowledge Validation & Trust Scoring, library-first) |
| Sprint 12 | Complete (merged — PR #13, `734aa2a`) (EPIC-05 — FEAT-05-4 Semantic Layer, storage-independent, library-first) |
| Sprint 13 | Complete (merged — PR #14, `a2ecbfe`) (EPIC-05 — FEAT-05-5 Knowledge Lifecycle & Versioning, storage-independent, library-first) |
| Sprint 14 | In Progress (**EPIC-13** — FEAT-13-1 Universal Connector Framework, storage/vendor/protocol-independent, library-first; additive roadmap — see note) |

Sprint scope for Sprint 4 onward follows the approved
`docs/architecture/EMG_Engineering_Backlog_v1.0.md` Sprint Planning table
(§6), not any simplified or alternate roadmap.

**Additive roadmap note — EPIC-13 (Sprint 14).** The frozen Engineering Backlog
defines EPIC-01 … EPIC-12 and, in particular, **EPIC-06 = Search** with
**FEAT-06-1 = Lexical Search**. The Universal Connector Framework is a **new,
additive** roadmap item: it was filed under the **next free identifiers
(EPIC-13 "Enterprise Integration Platform" / FEAT-13-1)** so that no existing
Backlog item is modified, renumbered, or overwritten. The frozen Backlog file
(`docs/architecture/EMG_Engineering_Backlog_v1.0.md`) is **unchanged** by this
sprint; EPIC-13 is recorded here (engineering status) and in the new library's
docs only. Delivered library-first as `libs/python/emg-connectors`: a
storage-, vendor-, and protocol-independent, contracts-only connector/plugin
framework — **no** networking, persistence, authentication, HTTP client, message
queue, cloud/vendor SDK, CLI, or UI, and **no vendor branching** in the core.
Real connectors (SAP, Oracle, SharePoint, Microsoft 365, Salesforce, ServiceNow,
Jira, …) are added as independently registered plugins without modifying the
framework. This sprint deliberately excludes dynamic plugin loading (filesystem
scanning, entry points, package installation, marketplaces, runtime code
execution); registration is in-memory only. Not wired into any service.
Post-review-fix refinements: standard capabilities stay the closed
`ConnectorCapability` enum while vendors declare additional capabilities via
free-form, namespaced `extension_capabilities` (no core change); and
`ConnectorPluginLoader` is the single source of truth for connector registration
and discovery (it auto-publishes/withdraws a plugin's connectors, eliminating the
loader/registry split).

**Sprint 5 scope note — FEAT-04-1 rescheduling.** The Backlog's Sprint 5 row
(§6) groups three features: FEAT-03-3, FEAT-03-4, and FEAT-04-1 (Audit Event
Pipeline). Sprint 5 as executed implemented only the two EPIC-03 authorization
features (FEAT-03-3, FEAT-03-4); FEAT-04-1 was rescheduled to the next Audit
implementation sprint (Sprint 6). This is an engineering sequencing decision
only: it does not modify the Architecture Baseline, does not redesign Module
6, and does not create or require a new ADR. The Backlog's feature-to-epic
assignments are unchanged; only the sprint in which FEAT-04-1 is built has
moved.

**Sprint 6 scope note — remaining EPIC-04 features shifted.** Sprint 6 as
executed implements **FEAT-04-1 only** (Audit Event Pipeline, satisfying
US-04). The Backlog's Sprint 6 row (§6) originally also grouped FEAT-04-2
(Provenance Record Model), FEAT-04-3 (Digital Evidence Chain-of-Custody), and
FEAT-04-4 (Audit Query & Reporting Interface); these three are shifted to
later Audit sprints as a continuation of the same engineering-sequencing
decision (FEAT-04-1 having moved into this sprint). This does not modify the
Architecture Baseline, does not redesign Module 6, does not alter the
Backlog's feature-to-epic assignments, and does not create or require a new
ADR — only the sprint in which each feature is built has moved. Sprint 6
implements the minimal query capability US-04 explicitly requires (by actor,
time range, and correlation identifier); the fuller FEAT-04-4 reporting
interface remains deferred.

**Sprint 7 scope note — approved controlled split of the remaining EPIC-04
features.** Sprint 7 implemented **FEAT-04-2 (Provenance Record Model)** and
**FEAT-04-3 (Digital Evidence Chain-of-Custody)** only, and **merged as PR #7**.
**FEAT-04-4 (Audit Query & Reporting Interface) was deferred** to the next
sprint (Sprint 8), which delivered it (merged as PR #8, `79eaae6`) before any
EPIC-05 / Module 7 work began. This was an engineering-sequencing decision only:
it did not modify the Architecture Baseline, did not redesign Module 6, and did
not create or require a new ADR. Provenance and chain-of-custody are already
within Module 6's frozen scope ("Audit, Provenance & Digital Evidence"; ADR-015,
ADR-016 §1). EPIC-04 was incomplete until FEAT-04-4 was delivered; with Sprint 8
merged, **EPIC-04 is now complete** and the EPIC-05 dependency gate (Backlog §7;
Master Plan §17 — "no module begins before every module it depends on has passed
acceptance") is **open**.

**Sprint 8 scope note — FEAT-04-4 completes EPIC-04.** Sprint 8 implements
**FEAT-04-4 (Audit Query & Reporting Interface)** only: classification-aware
audit + custody query filters, stable opaque-cursor keyset pagination, and
backend JSON/CSV report export — the "Backend query surface for audit records"
the Backlog (§3, line 109) defines for FEAT-04-4. It is additive and backward
compatible (existing Sprint 6/7 query shapes unchanged; a new index migration
`004` is index-only and touches no row or hash, so the golden hash gate stays
green). It reuses the existing `svc-audit` role and introduces **no new role,
no new ADR, no new service, and no UI** (backend only). Classification is a
*filter* dimension this sprint; clearance-based classification-aware read
*authorization* is a deliberate follow-up (it needs a human reader role and an
authorization decision) recorded in `docs/engineering/security-limitations.md`.
With FEAT-04-4 delivered, **EPIC-04 (Audit Platform) is functionally complete**
(FEAT-04-1 → FEAT-04-4), and the EPIC-05 dependency gate is unblocked for a
future sprint. This is engineering sequencing only: it does not modify the
Architecture Baseline or redesign Module 6. Sprint 8 **merged** as PR #8 (merge
commit `79eaae6`).

**Sprint 9 scope note — FEAT-05-1 Core Ontology, library-first.** Sprint 9
begins EPIC-05 (Knowledge Graph, Module 7) with **FEAT-05-1 (Core Ontology)
only**, following the same library-first pattern as Modules 5–6: a new
`libs/python/emg-ontology` package defines the governed ontology model — an
abstract `Entity` and the `Actor`/`Artifact`/`Event`/`Relationship` archetypes,
the **Organizational** and **Risk & Safety** domains (Backlog US-05, Module 7
§4) — where every entity carries `classification`, `trust_score`, and a
`provenance_reference` **by construction**, plus a pure, storage-independent
**conformance validator** and a deterministic, versioned ontology descriptor
(golden-tested). It reuses `emg_common_types.Classification`; the trust-score is
a required *field* only (scoring is FEAT-05-3). Provenance is a *reference* into
Module 6, never a copy. `services/knowledge-graph` **remains scaffolded** —
there is **no live service, no HTTP surface, and no Neo4j binding** this sprint
(persistence/ingestion is FEAT-05-2; the storage-independent semantic layer is
FEAT-05-4). **FEAT-05-2 through FEAT-05-5 are deferred.** This is engineering
sequencing within Module 7's frozen scope: it does not modify the Architecture
Baseline, does not redesign Module 7, introduces **no new role and no new ADR**,
and touches no Module 6 record or hash. Neo4j Enterprise remains the approved
future knowledge-graph store (Master Plan Technology Choice #4). Sprint 9
**merged** as PR #9 (merge commit `2fcbaa9`).

**Sprint 10 scope note — FEAT-05-2 Knowledge Ingestion Pipeline, library-first,
storage-independent.** Sprint 10 implements **FEAT-05-2 only**: the
**storage-independent ingestion pipeline** that converts validated ontology
models into persistent graph operations, delivered library-first as
`libs/python/emg-knowledge-pipeline`. It provides ingestion request models,
an ingestion context, an ingestion validator (ontology conformance + bounds +
duplicate/cycle checks — no persistence before validation), deterministic
idempotent id generation, entity/relationship resolvers, batch dependency
ordering, a `GraphStore` + transaction abstraction (rollback / no partial
graph) with an **in-memory adapter**, an ingestion result model, typed
ingestion errors, and **Module-6 audit-contract emission** for
`entity.created` / `relationship.created` / `entity.superseded` /
`relationship.superseded` (provenance referenced, correlation preserved, no
audit record duplicated). `owner`, `provenance_reference`, and `trust_score`
are **server-assigned** — caller-supplied values are not trusted; free-text is
length-bounded to prevent oversized-payload DoS; mass-assignment is rejected.
It is **storage-independent** (a `GraphStore` Protocol lets Neo4j be added later
without coupling business logic); there is **no Neo4j binding, no retrieval, no
search, no embeddings, no AI, and no UI** this sprint — the Neo4j adapter and
the Semantic Layer are FEAT-05-4. `services/knowledge-graph` remains scaffolded.
**FEAT-05-3/05-4/05-5 are deferred.** No new database, no new role, no new ADR,
no frozen-architecture change, and no Module 6 record or hash modified. Sprint 10
**merged** as PR #10 (merge commit `bf8d460`).

**Sprint 11 scope note — FEAT-05-3 Knowledge Validation & Trust Scoring,
library-first, deterministic.** Sprint 11 implements **FEAT-05-3 only**: the
composite confidence-scoring and advanced-validation ("quality gates") engine,
delivered library-first as `libs/python/emg-trust-scoring`. It provides a set of
trust **factors** (source confidence, provenance quality, evidence completeness,
validation status, ownership confidence, temporal freshness, relationship
consistency, ingestion quality), a **scoring policy** (per-factor weights, a
temporal-decay half-life, thresholds, and a pinned policy version), a
**deterministic scoring engine** that computes an immutable composite trust
score with a per-factor **explanation breakdown**, and a suite of typed
**quality-gate validation** checks (evidence completeness, provenance integrity,
ownership/identifier/ontology/relationship consistency, duplicate-confidence,
temporal, and lifecycle). Trust is **computed from observable signals** — a
caller supplies signals, never a trust value, so trust cannot be spoofed;
calculations are pure and reproducible and the output is frozen. It is a
**reusable library** with **no storage coupling, no persistence engine, and no
service**; there is **no Semantic Layer, no Neo4j, no retrieval, no graph
querying, no embeddings, no AI, and no UI**. Wiring this engine into the
ingestion pipeline in place of the FEAT-05-2 interim source-type default is a
follow-up for the future live ingestion service and is not done here (to avoid
changing merged FEAT-05-2 behaviour). `services/knowledge-graph` remains
scaffolded. **FEAT-05-4 and FEAT-05-5 are deferred.** No new database, no new
role, no new ADR, no frozen-architecture change, and no Module 6 record or hash
modified.

---

## Branch Strategy

```
main       — Production
develop    — Integration
feature/*  — Current development
```

---

## Rules

Architecture is frozen.

Engineering implements the architecture.

No redesign without ADR.

---

## Last Updated

Sprint 6 (`feature/sprint-6-audit-event-pipeline`, EPIC-04 Audit Platform —
FEAT-04-1 Audit Event Pipeline) **merged successfully** (PR #6, merge commit
`1fe6bc7`, → `develop`), delivering the library-first audit core
(`emg-audit-client`, `emg-audit-pipeline`) and `services/audit` as a minimal
live service owning the append-only PostgreSQL store, ingestion, minimal US-04
query, and integrity verification; the Sprint 6 security review concluded
**APPROVE WITH MINOR FIXES** and every required fix was resolved (see
`SPRINT-6-STATUS.md` §4b). Sprint 7 (`feature/sprint-7-audit-completion`,
FEAT-04-2 + FEAT-04-3) **merged** as PR #7. Sprint 8
(`feature/sprint-8-audit-query-reporting`, **FEAT-04-4 Audit Query & Reporting
Interface**) **merged** as **PR #8 (merge commit `79eaae6`)**, completing
**EPIC-04 (Audit Platform)** end to end (FEAT-04-1 → FEAT-04-4). Sprint 9
(`feature/sprint-9-core-ontology`, **FEAT-05-1 Core Ontology**) **merged** as
**PR #9 (merge commit `2fcbaa9`)**, delivering the governed ontology model,
the Organizational and Risk & Safety domains, and a pure conformance validator
(`libs/python/emg-ontology`). Sprint 10
(`feature/sprint-10-knowledge-ingestion`, **FEAT-05-2 Knowledge Ingestion
Pipeline**) **merged** as **PR #10 (merge commit `bf8d460`)** — a
**storage-independent** pipeline in `libs/python/emg-knowledge-pipeline` that
validates and persists ontology entities/relationships through a `GraphStore`
abstraction (in-memory adapter; no Neo4j binding), with deterministic idempotent
ids, transaction rollback (no partial graph), server-assigned
owner/provenance/trust, and Module-6 audit-contract emission. Sprint 11
(`feature/sprint-11-trust-scoring`) is **in progress**, adding **FEAT-05-3
(Knowledge Validation & Trust Scoring)** library-first in
`libs/python/emg-trust-scoring` — a **deterministic** trust-scoring +
advanced-validation engine that computes an immutable, explainable composite
confidence score from observable signals (never a caller-supplied trust value)
and runs typed quality-gate validation checks. It is a standalone library (no
persistence, no service, no Neo4j, no Semantic Layer, no retrieval/search/AI/UI);
wiring it into the ingestion pipeline is a follow-up for the future live
ingestion service. `services/knowledge-graph` remains scaffolded. No new
database, no new role, no new ADR, no frozen-architecture change, and no
Module 6 record or hash touched. Per the Definition of Done, formal
organizational Security Reviewer sign-off remains required before merge and is
not claimed here.

**Knowledge Graph Integration Closure, Groups A–C (2026-07-27).** Outside the
Sprint 1–14 / EPIC numbering above (a separate, targeted closure effort against
the already-live `services/knowledge-graph`, not a new Backlog sprint): Group A
(dependency/repository hygiene) and Group B (deployment readiness — Dockerfile,
migration entrypoint, seed data) were completed and validated first. **ADR-025
(Knowledge Graph Tenant & Authorization Model)** was then designed
(architecture-board-style review, repository-driven, no code changes) and
approved, and **Group C (Knowledge Graph Authorization Enforcement)**
implemented it exactly: the Query API's seven routes now call the platform's
existing Policy Enforcement Point (`emg-auth-client`) and ABAC evaluator
(`emg-policy-engine`) in the HTTP layer only, fail-closed and default-deny, with
a new platform-wide `PermissionDeniedError` (`emg-errors`) mapped to HTTP 403.
`emg_knowledge_graph` (the Query Engine / domain layer), `GraphStore`,
persistence, and the Neo4j projection were not modified — the existing
dependency-boundary test confirming this was re-verified as still passing.
Full pytest/ruff/black/mypy --strict/dependency-governance validation passed
repo-wide. Two small implementation-time findings and one still-open follow-up
(no registry-based allow-list of recognized Knowledge Graph API service
clients) are recorded in ADR-025 §18 and in
`services/knowledge-graph/README.md`'s "Authorization" section. Classification
enforcement (ADR-026 Revision 2) was completed separately and later the same
day (D1–D13; see the dedicated ADR-026 narrative above and OBS-A-004 in
`EMG_ARCHITECTURE_DECISION_REGISTER.md`). At the time of that 2026-07-27
closure, the Mutation API (ADR-027) and audit reconciliation (ADR-028) were out
of scope and had not begun; their current status is recorded in the ADR table
above.

**ADR-027 Revision 5 Stage 4 Phase 4A conformance closure (2026-08-01).**
PR #37 (merge commit `aefc82c`) merged the reconciled governance package
(`f59cb4b`) and narrow conformance patch (`0ea7c74`) into `develop`. Phase 4A
remains exactly the five mutation routes approved by ADR-027 Revision 5. The
closure records always-run compatibility normalization, accurate bearer and
effective-schema OpenAPI metadata, and focused transport/startup acceptance
evidence without changing commands, DTO semantics, domain logic, authorization
policy, GraphStore, persistence, or the mutation ledger. This closes only
ADR-027 Stage 4 Phase 4A: it does not start or define Phase 4B, start ADR-033
Phase 4, claim platform-wide production readiness, or authorize any UI surface.

**ADR-027 Revision 5 Stage 4 closure (2026-08-01).** Phase 4B mutation-path
observability emission was implemented at `c6c28bb` and merged through PR #45
at merge commit `6536b73`. Phases 4C and 4D remain closed as not required, and
Phase 4E completes the documentation-only governance and conformance closure.
ADR-027 Revision 5 Stage 4 is complete with exactly five mutation routes. The
BD-5 boundary remains unchanged: ADR-027 owns metric emission; ADR-015 /
FEAT-12-3 owns collection, storage, dashboards, tracing, and alerting. T-A-002
and T-A-003 remain Open and outside Stage 4; ADR-033 Revision 2 Phase 4 and
ADR-027 Stage 5 remain separate and unstarted.
