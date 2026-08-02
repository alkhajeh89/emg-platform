# EMG ADR-037 — Decision Domain Model

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-03
**Baseline:** `develop` at `dd84fa9`.
**Supersedes:** the EPIC-08 deferral recorded at
`libs/python/emg-ontology/src/emg_ontology/references.py:10-12`.
**Related:** ADR-023 (revision history), ADR-025 (authorization), ADR-026
Revision 2 (classification), ADR-027 Revision 5 (mutation surface), ADR-029
Revision 2 (identity, lifecycle, supersession), ADR-030 (mutation ledger),
Freeze §9, §14, §15, §23.

> **This ADR authorizes a domain contract only.** It implements no ontology
> code, adds no graph vocabulary, creates no route, and amends no accepted ADR.

---

## 1. Context

**FACT.** `emg-ontology/references.py:10-12` states: *"`Decision`,
`DecisionOption`, `DecisionRationale`, and `Approval` are intentionally NOT
modeled in Sprint 9: the approved scope excludes Decision Intelligence ontology
semantics (EPIC-08). They are added when that epic lands."*

**FACT.** `emg-memory-graph/enums.py:25` already defines
`NodeType.DECISION = "decision"`, and `:33` already defines decision-lineage
stages *Requirement → Meeting → Discussion → Decision*.

**FACT.** `emg-memory-graph.EdgeType` already contains every relationship this
model requires: `APPROVED`, `APPROVED_BY`, `SUPERSEDES`, `SUPERSEDED_BY`,
`EVIDENCED_BY`, `RESULTED_IN`, `DERIVED_FROM`, `SUPPORTS`, `AFFECTS`,
`PRECEDES`, `DISCUSSED_IN`, `HAS_PARTICIPANT`, `PART_OF`, `OWNS`, `OWNED_BY`.

**INFERENCE.** The gap is at the **governed ontology layer**, not the graph
substrate. Freeze §14 ("Memory Graph Entities — frozen, matches implemented
`emg-memory-graph`") is therefore untouched by this ADR.

**FACT.** Five of the six frozen Freeze §23 Executive Dashboard indicators are
non-computable without these entities (PD-001 §4).

## 2. Decision

### D-1 — Four ontology entities, minimum complete

Added to `emg-ontology` as governed entities. Minimum fields only.

| Entity | Purpose | Minimum fields |
| :--- | :--- | :--- |
| **`Decision`** | The governed act of deciding | `decision_id` (content-addressed per the `ids.py` convention); `title`; `statement`; `decided_at` (timezone-aware UTC); `owner`; `classification`; `status` ∈ {`proposed`, `decided`, `superseded`, `retired`}; `supersedes` (optional `decision_id`) |
| **`DecisionOption`** | An alternative that was considered | `option_id`; `decision_id`; `summary`; `selected: bool`; `classification` |
| **`DecisionRationale`** | Why the selected option prevailed | `rationale_id`; `decision_id`; `option_id` (optional); `narrative`; `classification` |
| **`Approval`** | Who authorized the decision | `approval_id`; `decision_id`; `approver`; `approved_at` (aware UTC); `outcome` ∈ {`approved`, `rejected`, `abstained`}; `classification` |

Identifiers are content-addressed and deterministic, following the existing
`emg-memory-graph/ids.py` convention. All timestamps are timezone-aware UTC,
following the platform canonicalization rule.

### D-2 — No new graph vocabulary

**No new `NodeType` and no new `EdgeType` is introduced.** The model is
expressed entirely in the frozen vocabulary:

```
Decision          --EVIDENCED_BY-->    EvidenceRef        (mandatory, D-3)
Decision          --HAS_PARTICIPANT--> Person
Decision          --APPROVED_BY-->     Person             (materialized by Approval)
Decision          --SUPERSEDES/-BY-->  Decision           (lifecycle, D-5)
Decision          --RESULTED_IN-->     Outcome / Project  (Freeze §23 indicator 2)
Decision          --DISCUSSED_IN-->    Meeting
Decision          --AFFECTS-->         Project / Policy   (Freeze §23 indicator 5)
DecisionOption    --PART_OF-->         Decision
DecisionRationale --SUPPORTS-->        DecisionOption
```

### D-3 — Evidence is mandatory

**A `Decision` must carry at least one `EvidenceRef`.** A `Decision` without
evidence cannot be constructed and is rejected at the domain boundary, not
merely flagged.

This makes the product's central promise structural: a decision that cannot be
evidenced does not exist in EMG. `DecisionRationale` may cite additional
evidence; `DecisionOption` and `Approval` may cite evidence but are not required
to.

### D-4 — Immutability

All four entities are immutable once asserted, following the existing evidence
rule (`emg-memory-graph/evidence.py:10-11`: *"Evidence is never mutated;
correcting evidence means adding a new `EvidenceRef`"*). Correction is by new
assertion, never by in-place edit.

### D-5 — Supersession

Lifecycle change is expressed by superseding assertion using the existing
`SUPERSEDES` / `SUPERSEDED_BY` edges and ADR-029 Revision 2 semantics. A
superseded `Decision` remains readable and auditable forever; its `status`
becomes `superseded` in the successor's revision. No decision is ever deleted.

### D-6 — Ownership

`Decision.owner` binds to the existing `owner_matches_principal` resource
attribute (`mutation_authorization.py:62-65`), which already resolves both
identity kinds — `Principal.subject` for humans and
`ServicePrincipal.client_id` for services (`:37-40`). **Human ownership
therefore works unchanged the day ADR-035 lands.** No new ownership mechanism is
introduced.

### D-7 — Classification

Each entity carries its own `Classification`. ADR-026 Revision 2 dominance
applies unchanged: a caller reads a `Decision` only if their clearance dominates
the maximum classification across the decision and every entity reachable in the
same response, including cited evidence. No new clearance rule, comparator, or
downgrade path is introduced.

### D-8 — Revisions

Decisions are asserted into the tenant graph and therefore inherit ADR-023
revision history — `list_revisions`, `get_revision`, `compare_revisions`, and
hash-verified historical reads — **with no new mechanism**. The question *"what
did we believe on date X"* is answered by the existing revision axis, not by a
new temporal field.

### D-9 — Audit

Creating, approving, superseding, or reclassifying a `Decision` is a **governed
action** and produces a `MutationAuditIntent` through the existing path
(`service.py:499-524`), persisted to the ADR-030 mutation ledger. No new audit
contract, event type, or ledger column is introduced.

### D-10 — No new mutation route

Decisions are entities and are created and replaced through the **existing five
ADR-027 Revision 5 routes** — `POST /api/v1/entities` and
`PUT /api/v1/entities/{entity_id}`. **No sixth route is introduced.** ADR-027's
five-route surface remains unchanged and authoritative.

### D-11 — Tenant scoping

All four entities are tenant-scoped exactly as every other persisted datum is.
No new isolation mechanism is introduced.

## 3. Non-goals — explicitly excluded

The following are **outside this ADR** and each requires its own decision when
that scope is opened:

- **Workflow engines** — no state machine, transition guard, or process
  orchestration.
- **Voting and quorum** — no vote counting, thresholds, or tie-breaking.
- **Delegation** — no proxy, deputy, or on-behalf-of approval.
- **Scoring** — no decision quality score, confidence ranking, or weighting.
- **Notifications** — no alerting, reminders, subscriptions, or digests.
- **SLA and deadline logic** — no due dates, escalation, or overdue tracking.
- **Multi-stage approval routing** — `Approval` records a single approver's
  outcome; sequencing is not modeled.
- Ontology **implementation code**, migrations, or API contracts.

## 4. Consequences

**Positive.** Unblocks Decision Explorer and four of the six frozen Freeze §23
dashboard indicators, completing a fifth. Requires no graph-schema change, so
Freeze §14 is untouched. Requires no new route, audit contract, classification
rule, or ownership mechanism — every cross-cutting concern is inherited.
Supersedes a deferral that had blocked the platform's central product promise.

**Negative — accepted.** `emg-ontology` gains four entities and its first
Decision-Intelligence semantics, widening that library's scope. The mandatory-
evidence rule (D-3) will reject decision capture attempts that would otherwise
succeed — deliberate, and the point of the model. Freeze §23 indicator 4
(knowledge-loss risk) remains blocked on an HR/leaver signal that this ADR does
not provide and no accepted source requires.

**Neutral.** No existing entity, route, or contract changes.

## 5. Acceptance criteria

- **AC-1.** All four entities are defined with the minimum fields in D-1.
- **AC-2.** A `Decision` cannot be constructed without at least one
  `EvidenceRef`.
- **AC-3.** **No new `NodeType` is introduced.**
- **AC-4.** **No new `EdgeType` is introduced.**
- **AC-5.** **No new mutation route is introduced**; ADR-027's five routes are
  unchanged.
- **AC-6.** All four entities are immutable; correction is by new assertion.
- **AC-7.** Supersession uses existing `SUPERSEDES`/`SUPERSEDED_BY` edges and
  ADR-029 semantics; no decision is deleted.
- **AC-8.** Ownership resolves through the existing `owner_matches_principal`
  attribute for both humans and services, with no new mechanism.
- **AC-9.** Classification enforcement is inherited from ADR-026 Revision 2
  unchanged; no new clearance rule exists.
- **AC-10.** Revision history is inherited from ADR-023 unchanged; no new
  temporal mechanism exists.
- **AC-11.** Every governed action produces a `MutationAuditIntent` through the
  existing path; no new audit contract exists.
- **AC-12.** All entities are tenant-scoped with no new isolation mechanism.
- **AC-13.** Every §3 exclusion is absent from the delivered model.
- **AC-14.** No ontology implementation code is authored by this ADR.
