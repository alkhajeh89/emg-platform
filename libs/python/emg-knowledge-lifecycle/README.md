# emg-knowledge-lifecycle

**Knowledge Lifecycle & Versioning** for Module 7 (Enterprise Knowledge Graph
Platform) — EPIC-05, **FEAT-05-5**, added Sprint 13.

Part of the EMG™ shared-libraries workspace (Module 3, ADR-012), delivered
**library-first**, **storage-independent**, and **deterministic**: it defines the
**managed lifecycle state machine** the ontology deferred, **immutable version
chains** with parent-child lineage, **deterministic transitions**, and **pure
retention / archive / restore evaluation**.

It **defines lifecycle semantics only — it executes nothing and stores nothing.**
There is **no persistence, no scheduler, no execution engine, no networking, no
Neo4j, no retrieval, no embeddings, no AI, no REST API, and no UI**.

## What this is

- **States + transitions** (`states.py`): `VersionState`
  (`proposed → active → deprecated → superseded → archived → retired`) and a
  **fixed, closed** transition table with `is_valid_transition` /
  `allowed_transitions`. This is the managed state machine `emg_ontology`
  deferred to FEAT-05-5; it aligns with `LifecycleStatus` and adds the
  operational states `deprecated`/`archived`.
- **Version model** (`identifiers.py`, `metadata.py`, `version.py`):
  `VersionIdentifier` (entity id + monotonic version), `VersionMetadata`
  (created-at, author, note), and the immutable `KnowledgeVersion` (identity,
  state, parent, effective window). Corrections are new versions, never in-place
  edits (append-only history).
- **Events** (`events.py`): `LifecycleEvent` — an immutable, self-validating
  record of one legal transition (it can only describe a permitted transition).
- **Chains + lineage** (`chain.py`): `VersionChain` — an immutable, validated
  history for one entity with bounded lineage helpers (`active`, `roots`,
  `latest`, `children`, `lineage`). Rejects mixed entities, duplicate versions,
  orphaned parents, more than one active version, and cycles.
- **Validation** (`validation.py`): `LifecycleValidator` with a non-raising
  `validate_chain(...) -> ChainValidationReport` (enumerates every issue as a
  typed `ChainIssue`), `assert_valid_chain(...)` / `assert_transition(...)`, and
  event enforcement `validate_event(...)` / `assert_event(...)`. Chain analysis is
  a single **O(N)** pass (a three-colour DFS over the parent graph) — the *same*
  algorithm the `VersionChain` constructor uses, so there is no duplicate cycle
  code and no quadratic traversal.
- **Policy** (`policy.py`): `LifecyclePolicy` (permitted transitions + a
  `require_reason` control that `validate_event` / `assert_event` **enforce**) and
  `RetentionPolicy` (per-state retention windows, archive delay, restore window),
  both immutable and versioned.
- **Retention evaluation** (`retention.py`): pure `evaluate_retention`,
  `evaluate_archive`, `evaluate_restore` returning immutable
  `RetentionDecision` / `ArchiveDecision` / `RestoreDecision`, computed against an
  explicit `as_of` (never a wall clock). Windows — including
  `restore_window_days` — are measured from a version's **effective-end
  reference** (`effective_to` if set, else `effective_from`), not from an archival
  timestamp (which this storage-independent library does not model).

## What this is not

- **Not a store, scheduler, or execution engine.** It holds no data, runs no
  jobs, and does no I/O. Nothing is executed on a version.
- **Not Neo4j, retrieval, embeddings, AI, an LLM, a REST API, or a UI** — and it
  is **not wired** into `emg-knowledge-pipeline`, `emg-trust-scoring`, or
  `emg-semantic-layer`. Those integrate only through future extension points.

## Bounds & security

- Models are **frozen** and **self-validating**; a malformed lifecycle model is
  rejected at construction (field/structure errors as `pydantic.ValidationError`;
  cross-model semantic errors as `LifecycleError` / `InvalidChainError` /
  `InvalidTransitionError`).
- **Deterministic transitions:** the transition relation is a fixed closed table
  — no caller-supplied rule, no arbitrary code, no escape hatch.
- **Linear-time, bounded validation:** chain size is hard-capped
  (`MAX_CHAIN_SIZE = 10_000`) and chain analysis is **O(N)** (a single
  three-colour DFS; each version is coloured at most once), so even a deep,
  maximal, legal chain validates in tens of milliseconds — no quadratic blow-up.
  Lineage walks are iterative and cycle-safe (a `visited` set), so they never
  recurse unboundedly or loop.
- **No injection surface:** identifiers/labels are validated by
  `ensure_safe_label` (empty/whitespace-only and NUL/ASCII-control/CR-LF/Unicode-
  bidi characters rejected; legitimate Unicode preserved).
- **Deterministic evaluation:** retention/archive/restore use an explicit `as_of`
  — no wall-clock, no randomness — so decisions are reproducible.

## Usage

```python
from datetime import datetime, timezone
from emg_knowledge_lifecycle import (
    VersionIdentifier, VersionMetadata, KnowledgeVersion, VersionChain,
    VersionState, LifecycleValidator, evaluate_archive, DEFAULT_RETENTION_POLICY,
)

t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
md = VersionMetadata(created_at=t0, author="svc-ingest")

v1 = KnowledgeVersion(
    identifier=VersionIdentifier(entity_id="ent-abc", version=1),
    state=VersionState.SUPERSEDED, metadata=md,
    effective_from=t0, effective_to=datetime(2026, 2, 1, tzinfo=timezone.utc),
)
v2 = KnowledgeVersion(
    identifier=VersionIdentifier(entity_id="ent-abc", version=2),
    state=VersionState.ACTIVE, metadata=md,
    parent=v1.identifier, effective_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
)

chain = VersionChain(versions=(v1, v2))          # validated: no cycle, one active
assert chain.active() is v2
assert LifecycleValidator.validate_chain((v1, v2)).valid

# Is v1 eligible to archive a year later? Deterministic, explicit as_of:
decision = evaluate_archive(v1, datetime(2027, 6, 1, tzinfo=timezone.utc))
print(decision.eligible, decision.reason)
```
