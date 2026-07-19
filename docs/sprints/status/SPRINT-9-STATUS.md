# Sprint 9 Completion Status — EPIC-05 Knowledge Graph, Core Ontology (FEAT-05-1)

**Status:** Sprint 9 — **Complete — pending merge.** Implements **FEAT-05-1
(Core Ontology)** only, the first EPIC-05 feature, **library-first** as
`libs/python/emg-ontology`. `services/knowledge-graph` remains scaffolded; there
is no live service, no HTTP surface, and no Neo4j binding this sprint. Nothing
committed, pushed, or merged.

**Branch:** `feature/sprint-9-core-ontology` (verified; based on `develop` at
the Sprint 8 merge, **PR #8, merge commit `79eaae6`**, which sits on Sprint 7
PR #7 and Sprint 6 PR #6 `1fe6bc7`).

**Repository:** `/Users/mak/Documents/GitHub/emg-platform`.

**Scope discipline:** engineering only, within Module 7's frozen scope — **no
Architecture Baseline change, no Module 7 redesign, no new ADR, no new role, no
new service, no UI, no Neo4j binding, no policy-engine / clearance enforcement.**

**DoD note:** this begins Module 7 (Knowledge Graph). Per Master Plan §15 /
Backlog §14 the merge still requires a formal organizational **Security Reviewer
sign-off**; none is claimed here.

## 0. Repository verification (performed before coding)

| Check | Result |
| --- | --- |
| Current branch = `feature/sprint-9-core-ontology` | ✅ |
| Working tree clean at start | ✅ |
| `git merge-base HEAD develop` = latest develop | ✅ `79eaae6` (branch freshly cut from develop) |
| Sprint 8 merge `79eaae6` (PR #8) present | ✅ |
| EPIC-04 complete through FEAT-04-4 | ✅ verified in code (`pagination.py`, `/events/page`, `/events/export`, `004_*.sql`) |

Findings surfaced: the five governance docs were **stale** (Sprint 8 "pending
merge" / old branch / "EPIC-04 incomplete") and were corrected first (§11 of the
approval). An unrelated filesystem artifact — untracked duplicate `services/* 2|3`
directories with **zero git-tracked files** — was noted; it is not part of the
branch and was left untouched.

## 1. Acceptance-Criteria Verification (US-05 / FEAT-05-1)

| # | Criterion (US-05, Backlog §5) | Status | Evidence |
| --- | --- | --- | --- |
| 5.1 | Core Ontology (Entity, Actor, Artifact, Event, …) implemented | Done | `core.py`; `test_core_envelope.py`, `test_domains.py::test_archetype_assignment` |
| 5.2 | Organizational domain implemented | Done | `organizational.py` (7 types); `test_domains.py` |
| 5.3 | Risk & Safety domain implemented | Done | `risk_safety.py` (6 types); `test_domains.py` |
| 5.4 | Every entity carries **classification** by construction | Done | required field (reused `emg_common_types.Classification`); `test_core_envelope.py::test_missing_classification_fails` |
| 5.5 | Every entity carries **trust score** by construction (field only) | Done | required bounded field; `test_core_envelope.py` trust-range tests (calc is FEAT-05-3, not done) |
| 5.6 | Every entity carries **provenance reference** by construction (into Module 6, not a copy) | Done | required `ProvenanceReference`; `test_core_envelope.py::test_provenance_reference_is_a_pointer_only` |
| 5.7 | An **ontology conformance test rejects a non-conforming write** | Done | `conformance.py`; `test_conformance.py` (every rejection category) |
| 5.8 | Governed relationship model with the approved catalog | Done | `relationships.py` (8 types); `test_relationships.py` |
| 5.9 | Deterministic, versioned ontology descriptor | Done | `descriptor.py`; `test_descriptor_golden.py` (golden gate) |
| 5.10 | Immutable history / no delete / no silent mutation | Done | frozen models + supersession; `test_core_envelope.py::test_supersession_creates_new_version_original_immutable` |

## 2. Ontology entity catalog (16 types)

**Core archetypes:** `Entity` (abstract) → `Actor`, `Artifact`, `Event`; plus
the governed `Relationship` model. Shared envelope on every entity: `entity_id`,
`entity_type`, `classification`, `trust_score` (0.0–1.0), `provenance_reference`,
`owner`, `lifecycle_status` (`proposed|active|superseded|retired`), `version`,
`effective_from`, `effective_to?`, `supersedes?`, `superseded_by?`,
`correlation_id?`.

| Entity | Archetype | Domain |
| --- | --- | --- |
| Organization | Actor | organizational |
| BusinessUnit | Actor | organizational |
| Person | Actor | organizational |
| Role | Actor | organizational |
| System | Actor | organizational |
| Project | Actor | organizational |
| Process | Actor | organizational |
| Risk | Artifact | risk_safety |
| Control | Artifact | risk_safety |
| Policy | Artifact | risk_safety |
| Regulation | Artifact | risk_safety |
| Incident | Event | risk_safety |
| Evidence | Artifact | risk_safety |
| AuditEventRef | Artifact | module6_reference |
| ProvenanceRecordRef | Artifact | module6_reference |
| CustodyRecordRef | Artifact | module6_reference |

Decision, DecisionOption, DecisionRationale, and Approval are **not** modeled
(EPIC-08 Decision Intelligence semantics, out of scope). The Module-6 reference
types are thin pointers (identifiers only; no audit content copied).

## 3. Relationship catalog (8 types)

| Type | Source → Target | Cardinality | Mutability |
| --- | --- | --- | --- |
| HOLDS | Person → Role | N:M | append_only |
| OWNED_BY | {Org, Person, Role, System, Project, Process, Risk, Control, Policy, Regulation, Incident, Evidence} → BusinessUnit | N:1 | mutable |
| MITIGATED_BY | Risk → Control | N:M | mutable |
| GOVERNS | Policy → {Process, System} | N:M | mutable |
| REQUIRES | Regulation → Control | N:M | mutable |
| DERIVED_FROM | Evidence → {System, Evidence, Incident} | N:1 | append_only |
| REFERENCES | {AuditEventRef, ProvenanceRecordRef, CustodyRecordRef} → Evidence | N:1 | append_only |
| IMPACTS | {Incident, Risk} → {Project, Process, System} | N:M | append_only |

Every relationship instance carries its own `classification`,
`provenance_reference`, `version`, effective dating, and supersession fields; all
are directed; self-loops prohibited by default.

## 4. Conformance-validation evidence

`conformance.py` is **pure and storage-independent**; it returns a typed
`ConformanceReport(ok, errors)` with machine-readable `ConformanceError(code,
message, location)`. Rejection codes exercised in `test_conformance.py`:
`ONTOLOGY_UNKNOWN_ENTITY_TYPE`, `…UNKNOWN_RELATIONSHIP_TYPE`,
`…MISSING_CLASSIFICATION`, `…MISSING_TRUST_SCORE`, `…TRUST_SCORE_OUT_OF_RANGE`,
`…MISSING_PROVENANCE`, `…INVALID_LIFECYCLE_STATE`, `…INVALID_SOURCE_TYPE`,
`…INVALID_TARGET_TYPE`, `…CARDINALITY_VIOLATION`, `…CLASSIFICATION_DOMINANCE`,
`…DANGLING_ENDPOINT`, `…SELF_LOOP_PROHIBITED`, `…INVALID_EFFECTIVE_DATES`,
`…EXTRA_FIELD` (mass-assignment). Accept paths and the raising helpers
(`assert_entity_conformant` / `assert_relationship_conformant` →
`OntologyConformanceError`, an `emg_errors.ValidationError` subclass) are also
covered. Endpoint classifications, the known-id universe, and sibling edges are
caller-supplied so the validator stays pure.

## 5. Golden descriptor evidence

`descriptor.py` generates the descriptor **from the authoritative code models**
(no RDF/OWL/SHACL/YAML). It is deterministic (sorted keys, stable separators):

- Pinned golden hash (`test_descriptor_golden.py::_GOLDEN_DESCRIPTOR_HASH`):
  **`5cbc5baa1ebadb52c65377b653b1d054d8aa2edae4a7e193f477b25585adf3b2`**
- Verified deterministic across repeated runs; `ontology_schema_version = 1`.
- This is a **merge-blocking gate** — the same pattern as the Module 6 golden
  audit hash. An unreviewed change to the ontology shape fails it.

## 6. Exact File List

**Created (23):**

```
SPRINT-9-STATUS.md                                              (this file)
docs/engineering/sprint-9-design.md
libs/python/emg-ontology/README.md
libs/python/emg-ontology/pyproject.toml
libs/python/emg-ontology/src/emg_ontology/__init__.py
libs/python/emg-ontology/src/emg_ontology/identifiers.py
libs/python/emg-ontology/src/emg_ontology/core.py
libs/python/emg-ontology/src/emg_ontology/organizational.py
libs/python/emg-ontology/src/emg_ontology/risk_safety.py
libs/python/emg-ontology/src/emg_ontology/references.py
libs/python/emg-ontology/src/emg_ontology/registry.py
libs/python/emg-ontology/src/emg_ontology/relationships.py
libs/python/emg-ontology/src/emg_ontology/conformance.py
libs/python/emg-ontology/src/emg_ontology/descriptor.py
libs/python/emg-ontology/src/emg_ontology/audit.py
libs/python/emg-ontology/tests/conftest.py
libs/python/emg-ontology/tests/test_import.py
libs/python/emg-ontology/tests/test_core_envelope.py
libs/python/emg-ontology/tests/test_domains.py
libs/python/emg-ontology/tests/test_relationships.py
libs/python/emg-ontology/tests/test_conformance.py
libs/python/emg-ontology/tests/test_descriptor_golden.py
libs/python/emg-ontology/tests/test_audit_contract.py
```

**Modified (7):**

```
ARCHITECTURE_STATUS.md, EMG_PRODUCT_VISION.md, README.md, CHANGELOG.md,
SPRINT-8-STATUS.md            (governance corrections — Sprint 8 merged / EPIC-04 complete / Sprint 9 in progress)
docs/engineering/testing-strategy.md, docs/engineering/security-limitations.md   (Sprint 9 sections)
```

**Deleted:** none (a `tests/__init__.py` created during development was removed
before it was ever committed, to avoid a pytest `tests.conftest` module-name
collision with `emg-audit-pipeline`; it never existed in a commit, so git shows
no deletion).

Counts: **23 created, 7 modified, 0 deleted** (verified via
`git status --porcelain --untracked-files=all`, excluding gitignored
`__pycache__`).

## 7. Quality-Gate Results

| Gate | Result |
| --- | --- |
| `pytest libs services --import-mode=importlib` | **398 passed, 16 skipped** (Sprint 8 baseline 287/16; **+111** new `emg-ontology` tests) |
| `ruff check` (emg-ontology) | **All checks passed** |
| `black --check --line-length 100` (emg-ontology) | **Clean** (19 files) |
| `mypy --strict` (emg-ontology/src) | **Success — no issues found in 11 source files** |
| Deterministic descriptor | **Verified** — identical hash across 3 runs (`5cbc5baa…adf3b2`) |
| Golden ontology descriptor gate | **Green** (`test_descriptor_golden.py`) |
| Module 6 golden audit-hash regression | **Green** — 6 tests; unchanged |
| Full Sprint 1–8 regression | **Green** (all prior suites pass unchanged) |
| JSON/YAML validation | N/A — no JSON/YAML added this sprint; `pyproject.toml` validated by the hatchling build |
| Secret/token leakage sweep | Clean — the only `SECRET` match is the `Classification.SECRET` enum rank; the only `Neo4j` match is a docstring noting it is out of scope. No secret/token literal, no Neo4j driver/Cypher. |

## 8. Scope Confirmation

- **FEAT-05-1 only.** No FEAT-05-2/03/04/05: no persistence, no ingestion, no
  trust-score calculation, no semantic/traversal layer, no lifecycle-state
  management.
- **`services/knowledge-graph` remains scaffolded** (`service.yaml`
  `status: scaffolded`, untouched).
- **No Neo4j binding** — no driver, Cypher, constraints, indexes, migrations,
  seed data, or repositories.
- **No Module 8–10 work** (`services/retrieval`, `ai-orchestration`,
  `decision-intelligence` untouched); no EPIC-06+.
- **No new role**, **no new ADR** (`docs/architecture/` untouched), **no new
  service**, **no UI**, **no policy-engine / clearance enforcement** (tagging by
  construction only).
- **No Module 6 record or hash modified** — the golden audit-hash gate is green;
  `emg-ontology` references Module 6 by identifier only.

## 9. Known Limitations & Deferred Features

Full detail in `docs/engineering/security-limitations.md` (Sprint 9 section):

- **Classification is a modeling attribute, not read enforcement.** No
  clearance-based traversal/read enforcement this sprint (no live surface). The
  substrate is in place (every node/edge classified; edge-dominance rule);
  runtime enforcement is FEAT-05-4 + the deferred clearance/role/ADR decision.
- **Trust score = stored field only** (calc is FEAT-05-3); **lifecycle status =
  validated field only** (management is FEAT-05-5).
- **Cardinality / dangling checks are context-supplied** — global graph-wide
  guarantees are the persistence/traversal layer's job (FEAT-05-2/05-4).
- **No audit emission** — the graph-mutation contract is defined; live delivery
  and any "fail-closed on degraded audit" decision are FEAT-05-2.
- **Deferred features:** FEAT-05-2 (ingestion + Neo4j binding), FEAT-05-3 (trust
  scoring), FEAT-05-4 (semantic layer), FEAT-05-5 (lifecycle). Modules 8–10 not
  started.

## 10. Suggested Commit Message

```
feat(knowledge-graph): Core Ontology model + conformance (FEAT-05-1, Sprint 9)

Begin EPIC-05 (Knowledge Graph, Module 7) with FEAT-05-1, delivered
library-first as libs/python/emg-ontology — the same contract-first pattern as
emg-policy-engine and emg-audit-client. No persistence, no live service, and no
Neo4j binding (those are FEAT-05-2 / FEAT-05-4).

- Core archetypes (Entity, Actor, Artifact, Event) + a governed Relationship
  model. Every entity requires, by construction, entity_id/entity_type/
  classification/trust_score/provenance_reference/owner/lifecycle_status/version/
  effective dating; models are frozen and extra="forbid".
- Organizational (Organization, BusinessUnit, Person, Role, System, Project,
  Process) and Risk & Safety (Risk, Control, Policy, Regulation, Incident,
  Evidence) domains, plus thin Module-6 reference types (AuditEventRef,
  ProvenanceRecordRef, CustodyRecordRef) — identifiers only, no audit content
  copied.
- Governed relationship catalog (HOLDS, OWNED_BY, MITIGATED_BY, GOVERNS,
  REQUIRES, DERIVED_FROM, REFERENCES, IMPACTS) with source/target types,
  cardinality, mutability, direction, and self-loop rules.
- Pure, storage-independent conformance validator returning typed,
  machine-readable errors (rejects unknown types, missing/invalid envelope,
  trust range, classification dominance, cardinality, dangling endpoints,
  self-loops, invalid effective dates, mass-assignment).
- Deterministic ontology descriptor generated from the authoritative code
  models (no RDF/OWL/SHACL/YAML), pinned ontology_schema_version, golden
  descriptor compatibility test (merge-blocking gate).
- Graph-mutation audit contract (definition only): entity.created/superseded,
  relationship.created/superseded; nothing emitted (no write service).

Trust score is a stored field only (calc is FEAT-05-3); lifecycle status is a
validated field only (management is FEAT-05-5); classification is tagging by
construction only (no PEP/clearance enforcement, no new role).

Governance docs corrected first: Sprint 8 merged (PR #8, 79eaae6), EPIC-04
complete, branch feature/sprint-9-core-ontology, Sprint 9 in progress.

Scope: FEAT-05-1 only. No FEAT-05-2/03/04/05, no Neo4j binding, no Modules 8-10,
no new role, no new ADR, no frozen-architecture change. services/knowledge-graph
remains scaffolded. No Module 6 record or hash modified.

Refs: FEAT-05-1, US-05, Module 7, Engineering Backlog v1.0 §3/§5/§6
```

## 11. Suggested Pull Request

**Title:** `Sprint 9: Core Ontology (FEAT-05-1) — EPIC-05 Knowledge Graph, library-first`

**Description:**

> Begins **EPIC-05 (Knowledge Graph, Module 7)** with **FEAT-05-1 (Core
> Ontology)**, delivered **library-first** as `libs/python/emg-ontology`. It is
> the governed ontology *model + conformance layer* — **no persistence, no live
> service, no Neo4j binding** (those are FEAT-05-2 / FEAT-05-4).
>
> **What's in this PR**
> - Core archetypes (`Entity` → `Actor`/`Artifact`/`Event`) + a governed
>   `Relationship` model, with the full governance envelope (classification,
>   trust score, provenance reference, owner, lifecycle, version, effective
>   dating) **required by construction**.
> - The **Organizational** and **Risk & Safety** domains (Module 7 §4), plus
>   thin **Module-6 reference** types (identifiers only — single system of
>   record).
> - A governed **relationship catalog** (8 types) with cardinality/mutability/
>   direction/self-loop rules.
> - A **pure, storage-independent conformance validator** with typed,
>   machine-readable errors — "rejects a non-conforming write" (US-05).
> - A **deterministic, versioned descriptor** generated from the code models,
>   guarded by a **golden gate**.
> - The graph-mutation **audit contract** (definition only).
>
> **What's explicitly NOT in this PR**
> - FEAT-05-2/03/04/05; the **Neo4j binding** (driver/Cypher/constraints/
>   indexes/migrations/seed/repositories); any live service, HTTP surface, auth,
>   or health endpoint; persistence; traversal/query; trust-score calculation;
>   lifecycle-state management; embeddings/search/AI; UI; any new role; any new
>   ADR; any policy-engine / clearance enforcement; any Module 8–10 work.
>   `services/knowledge-graph` stays scaffolded.
>
> **Governance (corrected first):** Sprint 8 merged (PR #8, `79eaae6`), EPIC-04
> complete, branch `feature/sprint-9-core-ontology`, Sprint 9 in progress,
> Module 7 in progress through FEAT-05-1. Frozen `docs/architecture/*`
> untouched.
>
> **Backward compatibility:** new isolated library; no Module 1–6 code, record,
> or hash touched — the **Module 6 golden audit-hash gate is green**.
>
> **Definition of Done:** this Module 7 change needs an organizational **Security
> Reviewer sign-off** before merge (not claimed here).
>
> **Quality gates:** pytest **398 passed / 16 skipped**, ruff clean, black clean,
> mypy --strict clean (11 files), deterministic + golden descriptor green,
> Module 6 golden hash green, secret sweep clean.

## 12. Confirmation

- **FEAT-05-2, FEAT-05-3, FEAT-05-4, FEAT-05-5 were not started.**
- **The Neo4j binding was not started** (no driver, Cypher, schema, migration,
  or seed data).
- **Sprint 10 was not started**; **Modules 8–10 were not started.**
- `services/knowledge-graph` remains scaffolded; no new role, no new ADR, no
  frozen-architecture document changed, no Module 6 record or hash modified.

---

**Stopping here per instruction: nothing has been committed, pushed, or merged.**
Sprint 9 (FEAT-05-1) is complete and awaiting review/approval.
