# ADR-027 Stage 1 Implementation Plan — Fine-Grained Mutation Commands

**Historical Status:**
- This was the approved pre-implementation plan.
- Stage 1 was later implemented.
- The implementation is tagged as adr-027-stage-1.
- This file is retained as a historical planning artifact.
- Instructions such as “do not begin implementation” are no longer active.

**Status:** Plan only. No code has been written. Do not begin implementation
until this plan is reviewed and approved, per standing instruction.
**Governing documents:** `docs/architecture/PROMPT_TEMPLATE_POST_ADR026.md`;
`docs/architecture/EMG_ADR-027_KNOWLEDGE_GRAPH_MUTATION_API.md` (Revision 2,
§5, §6, §7, §9, §11, §13, §14 item 2).
**Precondition:** Stage 0 complete (role catalog, idempotency migration);
GraphStore unification formally deferred (§4.7) and confirmed not to be a
dependency of this stage (§4.4).

---

## Scope

Stage 1 is application-layer only, per ADR-027 §14 item 2 and this session's
standing "no HTTP routes, no application commands beyond what's explicitly
scoped" discipline carried over from Stage 0. Concretely, Stage 1 adds:

- New command DTOs in `services/knowledge-graph/src/emg_knowledge_graph/commands.py`,
  alongside the existing `BuildRevisionCommand`/`RestoreRevisionCommand`.
- New orchestration methods on `KnowledgeGraphApplication`
  (`services/knowledge-graph/src/emg_knowledge_graph/service.py`), each
  reusing `MemoryGraphBuilder`/`GraphStore.transaction()` exactly as
  `build_revision` already does — no new write mechanism.
- Unit tests at the application layer only.

Stage 1 explicitly excludes (deferred to later stages per §14): HTTP routes
(Stage 4), authorization policy-rule data beyond what's needed to unit-test
command validation (Stage 2 owns the actual `PolicyRule` YAML), idempotency
lookup wiring (Stage 3 — though the `mutation_idempotency` table itself
already exists from Stage 0.3), and any `emg-knowledge-pipeline` change
(explicitly out of scope per the Stage 0.1 deferral, §4.7).

## Commands to add (§5.1's matrix, minus Bulk which is its own item)

Per ADR-027 §14 item 2, six entity-side commands plus relationship
equivalents:

1. `CreateEntityCommand` — `action=create`.
2. `UpdateEntityCommand` — `action=update`.
3. `RetireEntityCommand` — `action=retire` (soft delete; §9's lifecycle
   mapping: `ACTIVE → SUPERSEDED` via `emg_knowledge_lifecycle.states`,
   never a hard delete).
4. `RestoreEntityCommand` — `action=restore` (§9: `ARCHIVED → SUPERSEDED`
   only; never reinstates `ACTIVE` — a separate Create/Update is required
   for that, exactly as this ADR's Revision 2 already settled).
5. `MergeEntityCommand` — `action=merge`, reusing `emg-memory-graph`'s
   existing `EntityResolver` (union-find merge), never
   `emg-entity-resolution` (still an open, separately-tracked decision this
   ADR does not depend on).
6. `ReclassifyEntityCommand` — `action=reclassify`.
7. `CreateRelationshipCommand`, `UpdateRelationshipCommand`,
   `RetireRelationshipCommand` — relationship equivalents of 1–3 (no
   restore/merge/reclassify equivalent is defined for relationships in
   §5.1's matrix; only entities have those three operations).

Each command carries: `tenant`, `principal` (for the eventual PEP call in
Stage 4 — Stage 1 itself does not call the PEP, since there is no HTTP layer
yet to authenticate a caller against), the object payload, and — per §8.1 —
a caller-supplied `idempotency_key` field on the DTO now, even though Stage 1
does not yet look it up against `mutation_idempotency` (that wiring is
Stage 3). Including the field now avoids a later breaking DTO change.

## Application-layer methods

`KnowledgeGraphApplication` gains one method per command
(`create_entity(command: CreateEntityCommand) -> ...Result`, etc.), each:

1. Opens `GraphStore.transaction(tenant, principal)` (the same call
   `build_revision` already makes).
2. Reads the current snapshot (`transaction.read()`).
3. Builds the single changed node/edge via `MemoryGraphBuilder`/
   `MemoryNode.from_entity`/`MemoryEdge`-shaped construction — reusing
   `build_revision`'s exact conversion path, never a new one.
4. Stages the updated graph (`transaction.stage(graph)`).
5. Returns a result DTO wrapping the transaction's `WriteReceipt` on commit
   (mirroring `BuildRevisionCommand`'s existing result shape).

Soft-delete/restore methods additionally call
`emg_knowledge_lifecycle.states`'s transition validation before staging, per
§9's fixed transition table (`ACTIVE→SUPERSEDED` for retire,
`ARCHIVED→SUPERSEDED` for restore) — reusing the existing state machine,
never a new one.

Merge additionally calls `emg-memory-graph`'s existing `EntityResolver`
before staging the survivor node.

## What Stage 1 does NOT do (left to later stages, per §14)

- No `PolicyEnforcementPoint.authorize()` call — no caller identity exists
  yet to authorize at this layer (that composition happens at the HTTP
  layer, Stage 4, per §13's sequence). Stage 1's tests instead verify
  command-shape validation and the mutation's effect on the graph in
  isolation, the same testing posture ADR-024 §25 already established for
  Stage-1-shaped work ("command models, validation, and safety limits").
- No idempotency-key lookup against `mutation_idempotency` (Stage 3).
- No HTTP route (Stage 4).
- No `PolicyRule` YAML authoring (Stage 2).
- No change to `emg-knowledge-pipeline` (deferred, §4.7).

## Test plan

- Unit tests per command: valid construction, invalid/malformed payload
  rejection, correct `WriteReceipt`/result shape on a successful mutation,
  correct conflict behavior on a concurrent write (reusing the existing
  `PersistenceConflictError`/409-mapping test pattern already proven for
  `build_revision`).
- Soft-delete/restore: transition-table conformance tests (invalid
  transition, e.g. attempting `restore` on a `RETIRED` entity, is rejected
  with the existing typed lineage error from `emg-knowledge-lifecycle`).
- Merge: reuses `EntityResolver`'s own existing test doubles; asserts the
  survivor's classification is the maximum across inputs (§5.1's Merge
  clearance rule), even though the clearance *enforcement* itself is a
  Stage 2/4 concern — Stage 1 only needs to prove the classification-max
  computation is correct so Stage 4's authorization check has a correct
  value to compare against.
- All new tests run under the existing `emg-knowledge-graph`/
  `services/knowledge-graph` test suite; no new test infrastructure.

## Governance impact

No new package dependencies (this stays within `services/knowledge-graph`
and its existing `emg-platform-core`/`emg-memory-graph`/
`emg-knowledge-lifecycle` dependencies). `check_dependency_manifest.py`/
`check_dependency_drift.py`/`check_implicit_dependencies.py` are expected to
remain green with no manifest changes required.

## Review gate

Per standing instruction, this plan requires review and explicit approval
before any command/method is written. Stage 1 has not begun.

---

## Implementation Outcome

**Historical Status:** Stage 1 was fully implemented as planned. The application-layer commands, orchestration methods, and unit tests were successfully merged.
- Commit: `88397a69ea3440c8c1f71feb075b9073f5097e67`
- Tag: `adr-027-stage-1`
