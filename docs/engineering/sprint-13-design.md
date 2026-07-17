# Sprint 13 Design — Knowledge Lifecycle & Versioning (FEAT-05-5)

Reference: Engineering Backlog v1.0 §3 (FEAT-05-5 — "Knowledge Lifecycle &
Versioning: Proposed→active→retired state management"), §6 row 9, §8 (5 story
points); `emg_ontology.LifecycleStatus` (which carries a coarse lifecycle state as
a field and explicitly notes "the managed proposed→active→retired state machine is
FEAT-05-5 (deferred)"). Completes EPIC-05's knowledge-layer feature set
(FEAT-05-1 … 05-5) as libraries.

## Scope

Sprint 13 implements **FEAT-05-5 only**, delivered **library-first** as
`libs/python/emg-knowledge-lifecycle`: a **storage-independent, deterministic**
managed lifecycle state machine, immutable version chains with parent-child
lineage, and pure retention / archive / restore evaluation. It **defines lifecycle
semantics only — it executes nothing and stores nothing.**

Out of scope (deferred / excluded): persistence, any scheduler or execution
engine, networking, Neo4j, graph-database drivers, retrieval, embeddings, AI, LLM,
REST API, UI, and any authentication/authorization change. The library is **not
wired** into `emg-knowledge-pipeline`, `emg-trust-scoring`, or
`emg-semantic-layer`. `services/knowledge-graph` remains scaffolded.

## Architecture

Library-first and pure. The library depends only on `emg-common-types`,
`emg-errors`, and `pydantic` — **not** on `emg-ontology`,
`emg-knowledge-pipeline`, `emg-trust-scoring`, or `emg-semantic-layer` — so the
dependency direction stays clean and the library is reusable by any consumer.
Everything is a frozen pydantic model or a pure function; there is no I/O, no
wall-clock read, and no randomness.

**Relationship to `emg_ontology.LifecycleStatus`.** The ontology carries a coarse
lifecycle state (`proposed/active/superseded/retired`) as an entity *field* and
defers the *managed state machine* to FEAT-05-5. This library is that state
machine: it owns **which transitions are legal** and adds the operational states
`deprecated` and `archived`. It deliberately does **not** import the ontology
(keeping the dependency direction clean and the library reusable); the alignment
is documented, and mapping the managed state back onto an ontology entity's
`lifecycle_status` is a future binding concern.

## Lifecycle architecture

```
STATE MACHINE (fixed, closed table — deterministic, no arbitrary rule)
   proposed ─▶ active ─▶ deprecated ─▶ superseded ─▶ archived
        │         │           │             │            │
        ▼         ▼           ▼             ▼            ▼ (restore)
     retired   superseded  retired       retired ◀───── superseded
        │                                   │
        ▼                                   ▼
     archived                            archived

VERSION MODEL (immutable, self-validating, append-only lineage)
   VersionIdentifier(entity_id, version)  →  KnowledgeVersion(identifier, state,
   metadata, parent?, effective_from, effective_to?)   [parent = same entity,
   lower version]
        │
        ▼
   VersionChain(versions[])  — one entity; rejects mixed-entity, duplicate id,
   orphaned parent, >1 active, cycle; bounded lineage helpers (active, roots,
   latest, children, lineage)

VALIDATION
   LifecycleValidator.validate_chain(...)  → ChainValidationReport(issues[])   (non-raising, O(N))
   LifecycleValidator.assert_transition(from, to, policy)                      (raises)
   LifecycleValidator.validate_event/assert_event(event, policy)  enforces require_reason

POLICY + EVALUATION (pure; explicit as_of, never a wall clock)
   LifecyclePolicy(allow_restore, require_reason)     RetentionPolicy(windows)
        │                                                   │
        ▼                                                   ▼
   permits_transition(...)                     evaluate_retention/archive/restore(version, as_of, policy)
                                                     → RetentionDecision / ArchiveDecision / RestoreDecision
```

## Key decisions

- **Managed state machine as a fixed closed table.** Transitions are a constant
  relation (`states.py`); `is_valid_transition` / `LifecyclePolicy.permits_transition`
  are the only authorities. No caller-supplied rule and no arbitrary code, so a
  transition is either in the table (and enabled by policy) or rejected. A
  `LifecycleEvent` self-validates, so an illegal transition is not representable.
- **Append-only versioning.** A `KnowledgeVersion` is immutable; a correction is a
  new version whose `parent` is the same entity at a strictly lower version. This
  mirrors Module 6 / the ontology's append-only posture and makes cycles
  structurally impossible in normally-constructed data.
- **One O(N) analysis, two surfaces.** There is a single chain-analysis
  implementation — `validation.find_chain_issues`, an **O(N)** three-colour DFS
  over the parent "functional graph" (each version has ≤ 1 parent, so each node is
  coloured at most once). `LifecycleValidator.validate_chain` wraps it into a
  non-raising typed report; the `VersionChain` constructor calls the *same*
  function and raises `InvalidChainError` on the first issue. No duplicate cycle
  algorithm, and no quadratic per-node re-traversal. (Review fix: the earlier
  design re-walked the full lineage from every node — O(N²), ~40s at the size
  cap; the new pass validates a maximal chain in tens of milliseconds.)
- **Bounded by construction.** Chain size (`MAX_CHAIN_SIZE = 10_000`), version
  numbers, and retention windows are capped; the O(N) analysis makes even a
  maximal deep chain cheap, so the size cap is a sanity bound rather than a
  performance crutch. Lineage walks are iterative and cycle-safe (a `visited`
  set), so no unbounded recursion or looping.
- **Enforced transition policy.** `LifecyclePolicy.require_reason` is enforced by
  `LifecycleValidator.validate_event` / `assert_event` (raising
  `MissingReasonError` when a required reason is absent); a whitespace-only reason
  is rejected one layer earlier at event construction (safe-text).
- **Deterministic evaluation.** Retention/archive/restore take an explicit
  `as_of` and compute from a version's **effective-end reference** (`effective_to`
  if set, else `effective_from`); `restore_window_days` is measured from that
  reference, **not** from an archival timestamp (which this storage-independent
  library does not model — a future binding may supply a true `archived_at`).
  Identical inputs ⇒ identical, immutable decisions.
- **No injection surface.** Identifiers and free-text metadata pass
  `ensure_safe_label`, rejecting control/bidi characters while preserving
  legitimate Unicode.

## Security

- Immutable, self-validating models; malformed lifecycle models rejected at
  construction (`pydantic.ValidationError` for field/structure; `LifecycleError`
  / `InvalidChainError` / `InvalidTransitionError` / `MissingReasonError` for
  semantic).
- Deterministic transitions from a fixed closed table — no arbitrary execution.
- **Linear-time, bounded validation** — chain analysis is O(N), so a legal
  within-bounds chain cannot cause a quadratic denial-of-service; lineage walks
  are iterative and cycle-safe.
- Version-graph validation — cycles, orphans, duplicate-active, mixed-entity,
  invalid parents/timestamps/states all rejected.
- Identifier hardening — no control/bidi characters, no injection surface.
- The library validates and evaluates; it does not enforce runtime, schedule, or
  persist. Documented in `security-limitations.md`.

## Testing

See `testing-strategy.md` (Sprint 13 section): the golden transition table,
version/metadata/event validation and immutability, chain lineage + all structural
rejections (cycle, orphan, duplicate-active, mixed-entity, duplicate-id,
invalid-state), the typed validation report + deterministic issue ordering,
retention/archive/restore evaluation and determinism, `require_reason` event
enforcement, the typed unknown-lineage error, a **deep-chain O(N) performance
guard** (N = 8000, 5 s ceiling that the old O(N²) code would fail), and
adversarial inputs (control/bidi identifiers, extreme integers, oversized chains,
decision-forgery boundary) — plus the Module 6 golden audit-hash and Sprint 9
golden ontology descriptor regressions unchanged and the full Sprint 1–12 suite.
