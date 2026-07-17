# EMG™ Architecture Status

## Project Status

Architecture Phase: Frozen

Engineering Phase: Active

Current Branch: `feature/sprint-8-audit-query-reporting`

Current Sprint: Sprint 8 (complete — pending merge) — EPIC-04 completion,
FEAT-04-4 (Audit Query & Reporting Interface)

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
| Module 6 (Audit) | Implemented through FEAT-04-4 — FEAT-04-1/04-2/04-3 complete (merged, PRs #6/#7); FEAT-04-4 complete (Sprint 8, pending merge) | FEAT-04-1 (Sprint 6, PR #6); FEAT-04-2 + FEAT-04-3 (Sprint 7, PR #7); FEAT-04-4 (Audit Query & Reporting Interface — Sprint 8, pending merge) adds classification-aware audit + custody queries, opaque-cursor keyset pagination, and JSON/CSV report export (backend only, `svc-audit`, no new role/ADR). With FEAT-04-4 delivered, **EPIC-04 is functionally complete (FEAT-04-1 → FEAT-04-4)**; the EPIC-05 (Module 7) dependency gate is unblocked for a future sprint (see Sprint 8 scope note below). Clearance-based classification read *authorization* remains a documented follow-up (filter-only this sprint). |
| Module 7 (Knowledge Graph) | Scaffolded | `services/knowledge-graph/service.yaml`: `status: scaffolded`. No implementation yet. |
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
| Sprint 8 | Complete — pending merge (EPIC-04 completion — FEAT-04-4 Audit Query & Reporting) |
| Sprint 9 | Planned (EPIC-05 Knowledge Graph — now unblocked) |

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
features.** Sprint 7 implements **FEAT-04-2 (Provenance Record Model)** and
**FEAT-04-3 (Digital Evidence Chain-of-Custody)** only, and is **complete —
pending merge**. **FEAT-04-4 (Audit Query & Reporting Interface) is
explicitly deferred** to the immediate next sprint, which must deliver it
**before** EPIC-05 or any Module 7 work begins. This is an
engineering-sequencing decision only: it does not modify the Architecture
Baseline, does not redesign Module 6, and does not create or require a new
ADR. Provenance and chain-of-custody are already within Module 6's frozen
scope ("Audit, Provenance & Digital Evidence"; ADR-015, ADR-016 §1).
**EPIC-04 remains incomplete until FEAT-04-4 is delivered**, and the EPIC-05
dependency gate (Backlog §7; Master Plan §17 — "no module begins before
every module it depends on has passed acceptance") stays closed until then.

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
Architecture Baseline or redesign Module 6.

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
(`feature/sprint-8-audit-query-reporting`) is **complete — pending merge**,
delivering **FEAT-04-4 (Audit Query & Reporting Interface)** — classification-
aware audit + custody query filters, opaque-cursor keyset pagination, and
backend JSON/CSV report export (reusing `svc-audit`; no new role, ADR, service,
or UI). An independent architectural review at the start of Sprint 8 verified
the repository state directly (PR #6 and PR #7 merged; FEAT-04-1/04-2/04-3
implemented) and corrected a stale, red test-only assertion on the merged
mainline as a documented pre-condition. With FEAT-04-4 delivered, **EPIC-04
(Audit Platform) is functionally complete**; the EPIC-05 (Module 7) dependency
gate is unblocked for a future sprint. Per the Definition of Done, formal
organizational Security Reviewer sign-off is still required before merge and is
not claimed here.
