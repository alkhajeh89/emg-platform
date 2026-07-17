# EMG™ Architecture Status

## Project Status

Architecture Phase: Frozen

Engineering Phase: Active

Current Branch: `feature/sprint-10-knowledge-ingestion`

Current Sprint: Sprint 10 (in progress) — EPIC-05 Knowledge Graph, FEAT-05-2
(Knowledge Ingestion Pipeline)

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
| Module 5 (Authorization & Policy) | Authorization baseline complete through FEAT-03-4 | FEAT-03-1, FEAT-03-2 (Sprint 4); FEAT-03-3 (RBAC Baseline Roles), FEAT-03-4 (Authorization Testing Harness) (Sprint 5). `services/authz` remains scaffolded (library-first approach; see Sprint 4 and Sprint 5 design docs). FEAT-04-1 (Audit Event Pipeline), grouped with FEAT-03-3/03-4 in the Backlog's Sprint 5 row, is rescheduled to the next Audit sprint (see Sprint 5 scope note below) |
| Module 6 (Audit) | Complete through FEAT-04-4 — **EPIC-04 complete (merged)** | FEAT-04-1 (Sprint 6, PR #6, `1fe6bc7`); FEAT-04-2 + FEAT-04-3 (Sprint 7, PR #7); FEAT-04-4 (Audit Query & Reporting Interface — Sprint 8, **merged PR #8, merge commit `79eaae6`**) adds classification-aware audit + custody queries, opaque-cursor keyset pagination, and JSON/CSV report export (backend only, `svc-audit`, no new role/ADR). **EPIC-04 (Audit Platform) is complete (FEAT-04-1 → FEAT-04-4)**; the EPIC-05 (Module 7) dependency gate is unblocked. Clearance-based classification read *authorization* remains a documented follow-up (filter-only). |
| Module 7 (Knowledge Graph) | In Progress — FEAT-05-1 complete (merged); FEAT-05-2 (Knowledge Ingestion Pipeline) in progress (Sprint 10) | FEAT-05-1 (Core Ontology) merged (Sprint 9, PR #9, `2fcbaa9`) as `libs/python/emg-ontology`. Sprint 10 adds FEAT-05-2 **library-first** as `libs/python/emg-knowledge-pipeline`: a **storage-independent** ingestion pipeline (request models, validation, idempotent id generation, entity/relationship resolvers, batch dependency ordering, a `GraphStore`/transaction abstraction with an in-memory adapter, and Module-6 audit-contract emission) that turns validated ontology models into persistent graph operations. Owner/provenance/trust are **server-assigned** (never caller-supplied). `services/knowledge-graph` **remains scaffolded**; **no Neo4j binding** (the storage-independent Semantic Layer + Neo4j adapter is FEAT-05-4). FEAT-05-3/05-4/05-5 are deferred. |
| Module 8 (Search / GraphRAG / Retrieval) | Scaffolded | `services/retrieval/service.yaml`: `status: scaffolded`. No implementation yet. |
| Module 9 (AI Orchestration) | Scaffolded | `services/ai-orchestration/service.yaml`: `status: scaffolded`. No implementation yet. |
| Module 10 (Decision Intelligence) | Scaffolded | `services/decision-intelligence/service.yaml`: `status: scaffolded`. No implementation yet. |

A module's engineering status only advances when this repository proves it —
by committed, tested code — never by this document alone.

---

## ADRs

Only the following Architecture Decision Records are currently present in
`docs/architecture/`:

| ADR | Title | Status |
| --- | --- | --- |
| ADR-014 | Enterprise Presentation Architecture | Approved — Frozen |
| ADR-015 | Unified Enterprise Observability | Approved — Frozen |
| ADR-016 | Enterprise Ownership Registry | Approved — Frozen |
| ADR-017 | Enterprise Capacity & Scalability Model | Approved — Frozen |

ADR-001 through ADR-013 are **not present in this repository** and must not
be described as approved, frozen, or existing until they are actually added
under `docs/architecture/`.

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
| Sprint 10 | In Progress (EPIC-05 — FEAT-05-2 Knowledge Ingestion Pipeline, library-first) |
| Sprint 11 | Planned (EPIC-05 — FEAT-05-3 Knowledge Validation & Trust Scoring) |

Sprint scope for Sprint 4 onward follows the approved
`docs/architecture/EMG_Engineering_Backlog_v1.0.md` Sprint Planning table
(§6), not any simplified or alternate roadmap.

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
no frozen-architecture change, and no Module 6 record or hash modified.

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
(`feature/sprint-10-knowledge-ingestion`) is **in progress**, adding **FEAT-05-2
(Knowledge Ingestion Pipeline)** library-first in
`libs/python/emg-knowledge-pipeline` — a **storage-independent** pipeline that
validates and persists ontology entities/relationships through a `GraphStore`
abstraction (in-memory adapter; no Neo4j binding), with deterministic idempotent
ids, batch dependency ordering, transaction rollback (no partial graph),
**server-assigned** owner/provenance/trust, length-bounded free-text, and
**Module-6 audit-contract emission** (provenance referenced, correlation
preserved). `services/knowledge-graph` remains scaffolded; no retrieval, search,
embeddings, AI, or UI (those are EPIC-06+ / later EPIC-05 features). No new
database, no new role, no new ADR, no frozen-architecture change, and no
Module 6 record or hash touched. Per the Definition of Done, formal
organizational Security Reviewer sign-off remains required before merge and is
not claimed here.
