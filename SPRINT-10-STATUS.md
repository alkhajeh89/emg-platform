# Sprint 10 Completion Status — EPIC-05 Knowledge Graph, Knowledge Ingestion Pipeline (FEAT-05-2)

**Status:** Sprint 10 — **Complete — pending merge.** Implements **FEAT-05-2
(Knowledge Ingestion Pipeline)** only, **library-first** and
**storage-independent** as `libs/python/emg-knowledge-pipeline`.
`services/knowledge-graph` remains scaffolded; there is no Neo4j binding, no
live service, and no HTTP surface. Nothing committed, pushed, or merged.

**Branch:** `feature/sprint-10-knowledge-ingestion` (verified; based on
`develop` at the Sprint 9 merge, **PR #9, merge commit `2fcbaa9`**).

**Repository:** `/Users/mak/Documents/GitHub/emg-platform`.

**Scope discipline:** engineering only, within Module 7's frozen scope — **no
Architecture Baseline change, no Module 7 redesign, no new ADR, no new role, no
new database, no UI, no retrieval/search/embeddings/AI.**

**DoD note:** per Master Plan §15 / Backlog §14 the merge requires a formal
organizational **Security Reviewer sign-off**; none is claimed here. The
independent Sprint 10 review returned **APPROVE WITH MINOR FIXES**; the one
required fix (C1) is applied and verified below — the formal organizational
Security Reviewer sign-off nonetheless remains **outstanding** and is not
claimed.

## 0a. Sprint 10 review-fix round (C1 fixed; C2 deferred)

The independent architecture/security review flagged one item to fix before
merge, plus follow-up tests. Disposition:

- **C1 (fixed) — recursive cycle-detection DoS.** The ingestion validator's
  `_detect_cycle` used recursive DFS; a valid in-limit batch (a `DERIVED_FROM`
  chain deeper than Python's recursion limit but within
  `MAX_BATCH_RELATIONSHIPS`) could raise an uncaught `RecursionError`. It is
  **rewritten as an iterative explicit-stack DFS** with identical white/grey/
  black semantics and cycle-path return value. `MAX_BATCH_RELATIONSHIPS` was
  **not** reduced. Verified: a 5000-deep chain (unit) and a 1100-deep chain
  (end-to-end, within batch limits) validate without `RecursionError` and are
  accepted; the cyclic variants are still rejected with the typed
  `CODE_CYCLIC_DEPENDENCY`.
- **New adversarial tests added:** deep-chain no-recursion (unit + end-to-end),
  duplicate-relationship-in-batch, same-id-different-content conflict (store
  `GRAPH_ENTITY_CONFLICT` + pipeline validation rejection, original not
  overwritten), same-id-identical-content idempotency, and concurrent
  different-content-same-id (exactly one persists, no corruption, losers get a
  typed error).
- **C2 (deferred, not a blocker) — pre-commit created/skipped reporting and
  deduplicated double audit emission.** The `created`/`skipped` split in
  `IngestionResult` and the audit emission are computed from the pre-commit
  validation snapshot, so under a genuine race two callers can each report
  "created" for the same id and re-emit the (deterministic, Module-6-deduped)
  audit event. **The persisted graph is always correct** (lock-serialized,
  never forked/duplicated) and audit `event_id`s are deterministic so Module 6
  deduplicates. This is **not** fixed in this round (no transaction/audit
  redesign) and is recorded as deferred hardening: the store transaction should
  eventually report the *actually inserted* ids, and the ingestion result +
  audit emission should be based on the authoritative commit outcome — target
  phase: the **future persistent (Neo4j) adapter / live ingestion service**
  (FEAT-05-4 and the service). It is **not** claimed as fixed. See
  `security-limitations.md`.

## 0. Repository verification (performed before coding)

| Check | Result |
| --- | --- |
| Current branch = `feature/sprint-10-knowledge-ingestion` | ✅ |
| Working tree clean at start | ✅ |
| `git merge-base HEAD develop` = latest develop | ✅ `2fcbaa9` |
| Sprint 9 merge `2fcbaa9` (PR #9) present | ✅ |
| FEAT-05-1 complete (verified in code, not docs) | ✅ `emg-ontology` committed, 16 entities / 8 relationships, golden descriptor `5cbc5baa…` |

## 1. Acceptance-Criteria Verification (FEAT-05-2)

Backlog §6 row 8 exit criterion: **"Ingestion from at least one source type
validated end-to-end."** Met: the `system` source ingests entities +
relationships through validation → transactional persistence → audit emission
(`test_ingestion.py::test_successful_ingestion_persists_and_emits_audit`).

| # | Criterion (from the Sprint 10 scope) | Status | Evidence |
| --- | --- | --- | --- |
| 2.1 | Ingestion request models, context, result, typed errors | Done | `requests.py`, `context.py`, `result.py`, `errors.py`; `test_import.py` |
| 2.2 | Ingestion validator; **no persistence before validation** | Done | `validation.py`; `test_validation.py::test_unknown_entity_type_rejected_and_nothing_persisted` |
| 2.3 | Entity + relationship resolvers | Done | `resolver.py`; `test_ingestion.py` |
| 2.4 | Deterministic idempotent id generation; duplicate detection | Done | `idempotency.py`; `test_ingestion.py::test_idempotent_reingestion_creates_nothing` |
| 2.5 | Batch ingestion + dependency ordering (entities before relationships) | Done | `pipeline.py`; `test_concurrency_and_batch.py::test_batch_dependency_ordering_entities_before_relationships` |
| 2.6 | Transaction abstraction; rollback ⇒ no partial graph | Done | `graph_store.py`; `test_transactions.py` |
| 2.7 | Storage-independent graph persistence abstraction (in-memory adapter) | Done | `GraphStore`/`GraphTransaction` Protocols + `InMemoryGraphStore`; `test_import.py::test_in_memory_store_satisfies_graph_store_protocol` |
| 2.8 | Every request verified: conformance, uniqueness, relationship/identifier/provenance/classification/trust/ownership/effective-dates, duplicates, cycles | Done | `validation.py`; `test_validation.py`, `test_security.py` |
| 2.9 | Audit contracts for entity.created / relationship.created / entity.superseded / relationship.superseded; no duplicated records; provenance references; correlation preserved | Done | `audit.py`, `pipeline.py`; `test_audit_and_supersession.py` |
| 2.10 | Idempotency: repeated payload creates no duplicates; deterministic keys | Done | `test_ingestion.py`, `test_concurrency_and_batch.py::test_concurrent_identical_ingestion_collapses_to_one` |
| 2.11 | Security: server-assign owner/provenance/trust; reject caller values; max lengths; oversized-payload DoS prevention; reject mass-assignment | Done | `context.py`, `requests.py`, `validation.py`; `test_security.py` |

## 2. Architecture Summary

Library-first, storage-independent. Business logic depends only on the
`GraphStore`/`GraphTransaction` **Protocols**; Sprint 10 ships the append-only
`InMemoryGraphStore` adapter, and a Neo4j adapter can be added later (FEAT-05-4,
the Semantic Layer) by implementing the same Protocols — **no ingestion-logic
change, no second database**. The pipeline reuses `emg-ontology` (models +
conformance) and the completed EPIC-04 Audit Platform (`emg-audit-client`),
never a parallel record. Server-side authority (`IngestionContext`) assigns
`owner`/`provenance_reference`/`trust_score`; the request models structurally
cannot carry them. Deterministic ids give idempotency; one transaction per batch
gives atomicity (rollback ⇒ no partial graph); audit is emitted only after a
durable commit, and each node's `provenance_reference` points at its creation
audit event (single system of record).

## 3. Ingestion Architecture Diagram (text)

```
producer (system/document/api/ai/human)
   │  IngestionBatch(entities[], relationships[])  +  IngestionContext(server authority)
   ▼
KnowledgePipeline.ingest()
   ├─(1) validate_and_build         → bounds + mass-assignment reject + server-assign
   │                                   owner/trust/provenance/id + ontology conformance +
   │                                   relationship validity + dominance + cardinality +
   │                                   duplicate + dangling + cyclic DERIVED_FROM
   │                                   ──► ValidatedBatch  OR  raise IngestionValidationError
   │                                   (NO PERSISTENCE BEFORE VALIDATION SUCCEEDS)
   ├─(2) GraphTransaction           → begin → add_entity* → add_relationship* → commit()
   │                                   (atomic; entities before relationships;
   │                                    failure → rollback → NO PARTIAL GRAPH)
   ├─(3) emit audit (post-commit)   → AuditSink.record(SubmittedAuditEvent) → Module 6
   │                                   entity.created / relationship.created
   │                                   node.provenance_reference ──► this audit event
   │                                   correlation_id preserved
   └─► IngestionResult(created / skipped / emitted_audit_event_ids / correlation_id)

supersede_entity / supersede_relationship → entity.superseded / relationship.superseded (+ *.created)
```

## 4. Exact Files Created (25)

```
SPRINT-10-STATUS.md                                                        (this file)
docs/engineering/sprint-10-design.md
libs/python/emg-knowledge-pipeline/README.md
libs/python/emg-knowledge-pipeline/pyproject.toml
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/__init__.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/py.typed
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/errors.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/requests.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/context.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/idempotency.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/resolver.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/graph_store.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/validation.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/audit.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/pipeline.py
libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/result.py
libs/python/emg-knowledge-pipeline/tests/conftest.py
libs/python/emg-knowledge-pipeline/tests/test_import.py
libs/python/emg-knowledge-pipeline/tests/test_ingestion.py
libs/python/emg-knowledge-pipeline/tests/test_validation.py
libs/python/emg-knowledge-pipeline/tests/test_transactions.py
libs/python/emg-knowledge-pipeline/tests/test_security.py
libs/python/emg-knowledge-pipeline/tests/test_audit_and_supersession.py
libs/python/emg-knowledge-pipeline/tests/test_concurrency_and_batch.py
libs/python/emg-ontology/src/emg_ontology/py.typed                         (packaging fix — see §8)
```

## 5. Exact Files Modified (5)

```
ARCHITECTURE_STATUS.md            (Sprint 9 merged / EPIC-05 in progress through FEAT-05-2 / Sprint 10 scope note)
README.md                         (status line + Sprint 10 paragraph + /libs note)
CHANGELOG.md                      (Sprint 10 section; Sprint 9 marked merged PR #9)
docs/engineering/testing-strategy.md       (Sprint 10 testing section)
docs/engineering/security-limitations.md   (Sprint 10 controls + limitations)
```

**Deleted:** none. Counts: **25 created, 5 modified, 0 deleted** (verified via
`git status --porcelain --untracked-files=all`, excluding gitignored
`__pycache__`).

## 6. Quality-Gate Results

| Gate | Result |
| --- | --- |
| `pytest libs services --import-mode=importlib` | **444 passed, 16 skipped** (Sprint 9 baseline 398/16; **+46** `emg-knowledge-pipeline` tests, incl. the 7 review-round adversarial tests) |
| `ruff check` (emg-knowledge-pipeline) | **All checks passed** |
| `black --check --line-length 100` | **Clean** (19 files) |
| `mypy --strict` (emg-knowledge-pipeline/src) | **Success — no issues found in 11 source files**; emg-ontology re-checked clean (11) |
| Module 6 golden audit-hash regression | **Green** (6 tests) |
| Sprint 9 golden ontology descriptor regression | **Green**; descriptor hash unchanged (`5cbc5baa…adf3b2`) |
| Full Sprint 1–9 regression | **Green** |
| Secret/token leakage sweep | Clean — no secret/token literals; the only `Neo4j` match is a docstring noting it is out of scope |
| JSON/YAML validation | N/A — none added; `pyproject.toml` validated by the hatchling build |

## 7. Security Review

- **Server-side assignment (spoofing structurally impossible).** `owner`,
  `provenance_reference`, and `trust_score` are assigned from the
  `IngestionContext`; they are **not fields on the request models**, so a
  producer cannot supply them (verified `test_security.py`). `source_principal`
  is part of every deterministic id, so producers cannot overwrite each other's
  nodes.
- **Mass-assignment rejected** — request models `extra="forbid"`; an attempt to
  set a server/envelope field via `attributes` is a typed failure, not a silent
  drop.
- **Oversized-payload DoS prevention** — natural-key / attribute-value /
  attribute-count / batch-size bounds; over-limit input is rejected pre-work.
- **No persistence before validation; atomic rollback** — a failed or invalid
  batch leaves no partial graph and emits no audit (`test_transactions.py`).
- **Single system of record** — provenance is a *reference* into Module 6, no
  audit content copied; audit metadata carries identifiers/types only.
- **Known residual (documented, not a Sprint 10 defect):** trust is an interim
  source-type default (FEAT-05-3), classification is carried but reads are not
  clearance-enforced (no live surface; FEAT-05-4), cardinality is intra-batch
  only, and "fail-closed on degraded audit" is finalized with the live service.
  See `security-limitations.md`.

## 8. Known Limitations & Packaging Note

Full detail in `docs/engineering/security-limitations.md` (Sprint 10 section).
Highlights: in-memory graph adapter only (Neo4j is FEAT-05-4); trust is an
interim default (FEAT-05-3); supersession is a minimal primitive (lifecycle
management is FEAT-05-5); audit delivery is via an injected sink (a production
deployment injects a durable `AuditSink`).

**Packaging fix (documented):** adding the first downstream consumer of
`emg-ontology` surfaced that Sprint 9 shipped `emg-ontology` **without a
`py.typed` marker** (every other shared library has one). A zero-behavior fix —
an empty `py.typed` in `emg_ontology` (and in the new package) — was added so
`emg-ontology` is a properly-typed dependency and `mypy --strict` on the
consumer passes. No `emg-ontology` code, test, or golden descriptor changed
(descriptor hash unchanged).

## 9. Deferred Work

- **FEAT-05-3** Knowledge Validation & Trust Scoring (composite trust score).
- **FEAT-05-4** Semantic Layer (storage-independent query/traversal) **+ the
  Neo4j adapter** and clearance-based read enforcement.
- **FEAT-05-5** Knowledge Lifecycle & Versioning (managed proposed→active→retired,
  current-version resolution).
- A **live `services/knowledge-graph` ingestion service** (HTTP boundary, auth,
  durable audit sink, fail-closed-on-degraded-audit decision).
- EPIC-06+ and Modules 8–10 — not started.

## 10. Suggested Commit Message

```
feat(knowledge-graph): Knowledge Ingestion Pipeline (FEAT-05-2, Sprint 10)

Add the storage-independent Knowledge Ingestion Pipeline as a library-first
package (libs/python/emg-knowledge-pipeline) that converts validated
emg-ontology models into persistent graph operations, reusing the completed
EPIC-04 Audit Platform for mutation audit contracts. No Neo4j binding, no
retrieval/search/AI/UI, no new database; services/knowledge-graph stays
scaffolded.

- requests/context: producer requests carry no server-assigned field; the
  IngestionContext server-assigns owner/provenance_reference/trust_score
  (spoofing is structurally impossible). Free-text is length-bounded and the
  batch is size-capped (oversized-payload DoS prevention); mass-assignment is
  rejected.
- idempotency/resolver: deterministic entity/relationship ids from identity
  inputs (+ source_principal), so re-ingesting the same payload creates no
  duplicates and emits no new audit; endpoints resolve by (type, natural_key).
- validation: no persistence before validation succeeds — ontology conformance,
  relationship validity (endpoint types, classification dominance, intra-batch
  cardinality), uniqueness, dangling endpoints, and cyclic DERIVED_FROM are
  aggregated into typed problems.
- graph_store: storage-independent GraphStore/GraphTransaction Protocols + an
  append-only InMemoryGraphStore (no update/delete). Commits are atomic —
  rollback leaves no partial graph; concurrent identical ingestions collapse to
  one node.
- pipeline/audit/result: validate → order → persist (one transaction) → emit
  entity.created/relationship.created to an AuditSink; the node's
  provenance_reference points at that audit event (single system of record);
  correlation ids preserved. supersede_* emit the *.superseded contracts.

Packaging fix: add the missing py.typed marker to emg-ontology (Sprint 9
oversight) so it is a typed dependency; no ontology code/test/golden changed.

Governance: Sprint 9 merged (PR #9, 2fcbaa9), branch
feature/sprint-10-knowledge-ingestion, Module 7 in progress through FEAT-05-2.

Scope: FEAT-05-2 only. No FEAT-05-3/04/05, no Neo4j binding, no Modules 8-10,
no new role, no new ADR, no frozen-architecture change, no Module 6 record or
hash modified.

Refs: FEAT-05-2, Module 7, Engineering Backlog v1.0 §3/§6
```

## 11. Suggested Pull Request Title

`Sprint 10: Knowledge Ingestion Pipeline (FEAT-05-2) — storage-independent, library-first`

## 12. Suggested Pull Request Description

> Adds **FEAT-05-2 (Knowledge Ingestion Pipeline)** as a **library-first,
> storage-independent** package (`libs/python/emg-knowledge-pipeline`) that turns
> validated `emg-ontology` models into persistent graph operations and emits
> Module-6 audit contracts. **No Neo4j binding, no retrieval/search/AI/UI, no new
> database**; `services/knowledge-graph` stays scaffolded.
>
> **What's in this PR**
> - Ingestion request models + context (server-assigned owner/provenance/trust —
>   caller values are structurally impossible), deterministic idempotent ids,
>   entity/relationship resolvers.
> - An ingestion validator that runs **before any persistence**: ontology
>   conformance, relationship validity, classification dominance, intra-batch
>   cardinality, uniqueness, dangling endpoints, cyclic `DERIVED_FROM`, bounds
>   and mass-assignment rejection.
> - A storage-independent `GraphStore`/`GraphTransaction` abstraction + an
>   append-only `InMemoryGraphStore`; atomic commit with **rollback ⇒ no partial
>   graph**; concurrent identical ingestions collapse to one node.
> - Pipeline orchestration + typed `IngestionResult` + audit emission
>   (`entity.created` / `relationship.created`, and `*.superseded` via the
>   minimal supersession primitives); provenance references the audit event
>   (single system of record); correlation ids preserved.
>
> **What's explicitly NOT in this PR**
> - The **Neo4j binding** and Semantic Layer (FEAT-05-4); trust-score
>   calculation (FEAT-05-3); lifecycle management (FEAT-05-5); any live service,
>   HTTP surface, retrieval, search, embeddings, AI, or UI; any new database,
>   role, or ADR; any Module 8–10 work.
>
> **Packaging fix:** added the missing `py.typed` marker to `emg-ontology` (a
> Sprint 9 oversight) so it is a typed dependency — no ontology code/test/golden
> descriptor changed (hash unchanged).
>
> **Backward compatibility:** a new isolated library; no Module 1–6 code,
> record, or hash touched — the **Module 6 golden audit-hash** and **Sprint 9
> golden ontology descriptor** regressions are green.
>
> **Definition of Done:** this Module 7 change needs an organizational **Security
> Reviewer sign-off** before merge (not claimed here).
>
> **Quality gates:** pytest **437 passed / 16 skipped**, ruff clean, black clean,
> mypy --strict clean (11 files), golden regressions green, secret sweep clean.

---

**Stopping here per instruction: nothing has been committed, pushed, or merged.**
Sprint 10 (FEAT-05-2) is complete and awaiting review/approval.
