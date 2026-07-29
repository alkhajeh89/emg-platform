# ADR-029 — Canonical Entity and Relationship Identity, Lifecycle, and Supersession Model

**This ADR was approved as a prerequisite for ADR-027 Revision 3 and remains
the domain authority consumed by ADR-027 Revision 5.** It does not modify
ADR-027. Produced under
`docs/architecture/PROMPT_TEMPLATE_POST_ADR026.md`.

## 1. Title

Canonical Entity and Relationship Identity, Lifecycle, and Supersession
Model — the foundational contract ADR-027's Mutation API (Retire, Restore,
Update, Merge, and relationship-validity closure) will consume.

## 2. Status

**Accepted — Revision 2 (Architecture Board approval: 2026-07-28).**
Implemented at commit `97b211d` and tagged
`adr-029-approved-implementation`. The architecture was produced following a four-stage
investigation: (1) discovery that ADR-027 §9/§5.1 assumed a mechanism that
does not exist (`EMG_ADR-027_STAGE_0_1_GRAPHSTORE_UNIFICATION_ANALYSIS.md`
established the pattern of stopping before coding an unreviewed mechanism);
(2) confirmation that the gap spans lifecycle, versioning, and merge, not
versioning alone; (3) a scope analysis determining that identity, lifecycle,
and supersession (including merge as its many-to-one case) are one entangled
decision, while graph revisions, temporal validity, and the general
immutable-replacement principle are already settled and out of scope; (4)
Revision 1 of this document, drafting that decision. An independent
Architecture Review Board pass returned **PASS WITH REQUIRED CHANGES**,
accepting the architectural direction (identity preservation, minimal
`MemoryNode` extension, `VersionState` reuse, derived `superseded_by`, Merge
as many-to-one supersession, zero change to `GraphStore`/revisions) while
requiring nine specific gaps to be closed before acceptance: the omitted
`owner` field, `VersionState` reachability, supersession integrity
invariants, an unbounded `supersedes` field, an incomplete Merge field
specification, unresolved relationship-identity/endpoint-change rules, an
unresolved archived-source-merge ambiguity, unstated rollback semantics, and
a terminology collision with ADR-023's "Restore." This revision (Revision 2)
resolves all nine without reopening any decision the review accepted — see
the accompanying Changelog. Not yet re-reviewed or accepted by the
Architecture Board.

**Date:** 2026-07-27
**Deciders:** Principal Software Architect / Architecture Board (EMG
Platform)
**Baseline:** `adr-027-complete` plus Stage 0 (role catalog,
`mutation_idempotency` migration)
**Related:** ADR-022 (Revision Build Workflow), ADR-023 (Revision History &
Navigation), ADR-024 (Query Engine), ADR-025/026 (Tenant/Authorization,
Classification), ADR-027 (Revision 2, Knowledge Graph Mutation API — the
consumer this ADR exists to unblock)
**Explicitly does not supersede or reopen:** ADR-022/023 (revision model,
history navigation), ADR-024 (query algorithms), ADR-025/026 (authorization,
classification), or any part of ADR-027 not explicitly cited here. ADR-027
itself is revised separately, after this ADR is accepted.

---

## 3. Context

ADR-027 Revision 2 was approved (PASS) and began implementation. Stage 0's
two mechanical items (role catalog, idempotency migration) completed
cleanly. Attempting to scope Stage 0.1 (GraphStore unification) and then
Stage 1 (fine-grained mutation commands) surfaced, in sequence: a genuine
GraphStore-shape mismatch (deferred, §4.7 of ADR-027, unrelated to this
document); then five confirmed contradictions in ADR-027's own soft-delete
and merge design — lifecycle state is not preserved through `MemoryNode`,
`GraphStore` persists whole-snapshot content that cannot represent an
in-place lifecycle change, the builder's merge rules treat `validity` and
`classification` as immutable (blocking exactly the changes ADR-027 needs),
incident-relationship validity cannot be closed with any existing mechanism,
and `EntityResolver` is not a merge engine. Two further investigation
rounds established that this is not a narrow "versioning" gap but a genuine
absence of a canonical identity/lifecycle/supersession model spanning three
independently-built layers (Ontology, Knowledge Lifecycle, Memory Graph)
that were never integrated for this purpose.

## 4. Problem Statement

Three models exist in the repository that each address part of "how does an
entity or relationship change over time," and none of them, alone or
combined, is both correct in shape and reachable at the point where a
mutation actually happens:

- **Ontology** (`emg_ontology.core.Entity`/`Relationship`): carries
  `lifecycle_status` (`LifecycleStatus`, four values), `supersedes`,
  `superseded_by`, `effective_from`, `effective_to`. Frozen. Transient — used
  only during ingestion construction, then discarded; never the object read
  back for a mutation.
- **Knowledge Lifecycle** (`emg_knowledge_lifecycle`): `KnowledgeVersion`
  (`identifier`, `state: VersionState` — six values, including `DEPRECATED`
  and `ARCHIVED` which `LifecycleStatus` lacks — `metadata`, `parent`,
  `effective_from`, `effective_to`) and `VersionChain` (a real, working,
  tested lineage/transition-validation mechanism). Deliberately built
  without an `emg-ontology` dependency. Not consumed by any other package
  today.
- **Memory Graph** (`emg_memory_graph.nodes.MemoryNode`/`edges.MemoryEdge`):
  the object actually persisted via `GraphStore` and read back for every
  query and every mutation. Carries neither a lifecycle field, a
  supersession field, nor an `owner` field. `MemoryNode.from_entity()` is
  confirmed, deliberately lossy with respect to all of the above.

No mutation-capable operation can be correctly designed against this state
without first resolving one canonical answer to identity, lifecycle, and
supersession — the exact conclusion of the immediately preceding scope
analysis, now formalized as this ADR's Final Decision.

## 5. Repository Evidence

Confirmed by direct source reads (not documentation claims), across this
investigation:

- `libs/python/emg-ontology/src/emg_ontology/core.py` — `Entity` (109–143)
  and `Relationship` (170–200), both `frozen=True`. `LifecycleStatus` (four
  values: `PROPOSED`, `ACTIVE`, `SUPERSEDED`, `RETIRED`). No `ARCHIVED`. No
  `supersede`/`next_version`/`retire`/`restore`/`clone` constructor
  anywhere in the package (confirmed by an exhaustive grep). `supersedes`/
  `superseded_by` are declared fields never populated by any library code —
  the only place either is set is a test fixture.
- `libs/python/emg-knowledge-lifecycle/src/emg_knowledge_lifecycle/states.py`
  — `VersionState` (six values), `_TRANSITIONS` (a fixed, closed table),
  `is_valid_transition`/`allowed_transitions`, `LIVE_STATES`. Explicitly
  does not import `emg_ontology` ("to keep the dependency direction clean
  and the library reusable," states.py's own docstring), and documents an
  *intended*, not-yet-wired alignment: "ontology PROPOSED ==
  VersionState.PROPOSED ... DEPRECATED, ARCHIVED are managed-lifecycle
  refinements with no ontology field."
- `libs/python/emg-knowledge-lifecycle/src/emg_knowledge_lifecycle/version.py`
  — `KnowledgeVersion` (22–32): `identifier`, `state`, `metadata`, `parent`,
  `effective_from`, `effective_to`. Linking is a single forward `parent`
  pointer, not a `supersedes`/`superseded_by` pair.
- `libs/python/emg-knowledge-lifecycle/src/emg_knowledge_lifecycle/chain.py`
  — `VersionChain.lineage()` (73–90) derives ancestry by walking `parent`
  pointers on the newer object; nothing is ever written onto an
  already-constructed predecessor.
- `libs/python/emg-memory-graph/src/emg_memory_graph/nodes.py` — `MemoryNode`
  (31–48): `node_id`, `node_type`, `label`, `created_at`, `updated_at`,
  `source`, `confidence`, `classification`, `evidence`, `aliases`,
  `histories`, `ontology_entity_id`, `metadata`. No lifecycle, supersession,
  or owner field. `from_entity()` (88–117) does not map
  `Entity.lifecycle_status`/`supersedes`/`superseded_by`/`owner` anywhere.
- `libs/python/emg-memory-graph/src/emg_memory_graph/edges.py` — `MemoryEdge`
  (29–45), `frozen=True`, no mutator. Docstring (6–7): "changing a
  relationship means adding a new edge and closing the old one's validity
  ... never mutating in place" — the intended pattern, not yet
  mechanically supported.
- `libs/python/emg-memory-graph/src/emg_memory_graph/builder.py` —
  `_edge_immutable_fields`/`_validate_edge_group` (358–389) raise
  `MergeConflictError` if a resubmitted `EdgeInput` under the same
  `edge_id` differs in `validity` or `classification`; `_merge_edge`
  (316–356) additionally always keeps `existing.validity`, discarding any
  incoming value. `_merge_node` (267–314) has no equivalent immutable-field
  check — `classification` is silently overwritten by whichever input is
  newest.
- `libs/python/emg-memory-graph/src/emg_memory_graph/temporal_query.py` —
  `active_edges_at` (33–35) is a pure, read-only filter.
- `libs/python/emg-memory-graph/src/emg_memory_graph/resolution.py` —
  `EntityResolver.resolve()` (205–254) operates on `EntityMention(mention_id,
  entity_type, label)` → `ResolvedEntity(canonical_id, canonical_label,
  member_mention_ids)` — pure label clustering, never imported by
  `builder.py`, no interaction with stored `MemoryNode`s, evidence, edges,
  or classification.
- **`libs/python/emg-memory-graph/pyproject.toml` already declares
  `emg-knowledge-lifecycle` as a dependency** — confirmed present in its
  `dependencies` list — but grepping `emg-memory-graph`'s entire source
  confirms zero actual imports of `emg_knowledge_lifecycle` anywhere (unlike
  `emg_trust_scoring`/`emg_semantic_layer`, both genuinely imported and
  used). The edge this ADR needs was **already anticipated and declared**,
  never consumed. This is independent, concrete evidence for §4's
  "intended convergence, never completed" reading, not an inference.
- `LifecycleStatus`'s entire real-code blast radius, repo-wide, is two call
  sites — `emg_knowledge_pipeline/pipeline.py:137` and `validation.py:119`
  — both hardcoding `LifecycleStatus.ACTIVE`.

## 6. Constraints

- Must not modify `GraphStore`, the revision/concurrency model (ADR-022/023),
  temporal validity's existing design (`TemporalValidity`, `active_edges_at`),
  authorization, idempotency, the HTTP API, the Query Engine's existing
  algorithms, or `emg-entity-resolution` — all explicit non-goals, none
  implicated by the confirmed evidence.
- Must preserve every existing `frozen=True` contract — no mutation method
  is introduced anywhere.
- Must preserve `emg-knowledge-lifecycle`'s no-`emg-ontology`-import
  discipline.
- Must not introduce a second, parallel classification-visibility mechanism
  alongside ADR-026's existing gate.
- Must not duplicate `_merge_evidence`, `is_valid_transition`, or any other
  already-correct pure function — reuse, never reimplement.
- Backward compatibility: every existing `MemoryNode`/`MemoryEdge`
  construction call site and every historical `graph_revisions.graph_json`
  row must remain valid without modification.

## 7. Alternatives Considered

**A. Extend `emg_ontology.LifecycleStatus` to six values and treat it as
canonical everywhere, including on `MemoryNode`.** Rejected. `Entity` is a
transient, discarded-after-ingestion DTO — the type nothing actually reads
back. Making it "canonical" for the Mutation API would still require
carrying its value forward onto `MemoryNode` regardless, so this alternative
does not avoid the `MemoryNode` extension this ADR makes; it only adds an
unnecessary, unjustified change to a four-consumer... in fact two-call-site
type for no benefit.

**B. Adopt `emg-knowledge-lifecycle`'s full `KnowledgeVersion`/
`VersionIdentifier`/`parent`/`VersionChain` machinery wholesale as
`MemoryNode`'s versioning representation, replacing flat `node_id` identity
with a compound `(entity_id, version)` identifier.** Considered seriously —
it is the most complete, already-built, already-tested mechanism available,
including cycle/orphan detection this ADR's own design lacks. Not selected
for this revision because it requires changing `MemoryGraph`'s fundamental
identity model (one live entry per `node_id`, a dict-keyed structure
throughout `builder.py`) to a compound key — a strictly larger, riskier
change than the confirmed evidence requires, and outside this ADR's
constraint to preserve `MemoryGraph`'s existing structure. Recorded as a
**Deferred Decision** (§18), not rejected outright — a future need for
`VersionChain`'s validation guarantees (e.g. cycle detection across many
merges) may justify revisiting this.

**C. Bridge/reconcile the three models via an adapter that translates
between them at read/write time, keeping all three unchanged.** Rejected —
same reasoning ADR-027 §4.2 already applied to an equivalent choice for
`GraphStore`: an adapter perpetuates drift rather than eliminating it, and
still requires `MemoryNode` to carry *some* representation of the
translated value, so it does not avoid the extension below; it only adds an
unnecessary translation layer.

**D. Minimal, additive extension of `MemoryNode`/`MemoryEdge` with a new
builder construction path, reusing `VersionState`/`is_valid_transition`/
`_merge_evidence` from the already-correct libraries, without touching
`emg-ontology` or `emg-knowledge-lifecycle`'s existing code.** **Selected.**
Smallest change consistent with the confirmed evidence; uses the
already-declared-but-unconsumed `emg-memory-graph` → `emg-knowledge-lifecycle`
dependency edge rather than inventing a new one; preserves every existing
frozen contract and every non-goal in §6.

## 8. Final Decision

Adopt Alternative D. `MemoryNode` becomes the single, canonical, persisted
carrier of lifecycle and supersession state, using `emg_knowledge_lifecycle.VersionState`
as its lifecycle enum. `emg_ontology.LifecycleStatus` is left entirely
unmodified, continuing to serve only its existing, narrow, two-call-site
ingestion role. A new `MemoryGraphBuilder` construction path — distinct
from `build`/`extend`/`from_ontology`'s existing merge logic — performs
authorized, single-object replacement for lifecycle-class changes and
relationship-validity closure. Merge Entity is redesigned as the many-to-one
case of the same supersession mechanism, decoupled from `EntityResolver`.

---

## 9. Identity Model

**Entity identity** is `MemoryNode.node_id` (unchanged, `SafeLabel`-typed).
A lifecycle-class change (Retire, Restore, Reclassify, ordinary Update)
**preserves identity**: the same `node_id` is replaced with new field
values in the next graph revision — never assigned a new id, never removed
from the graph. Identity is destroyed or reassigned by no operation this
ADR defines; even a source entity absorbed by Merge keeps its own
`node_id`, transitioned to a non-live lifecycle state, never deleted or
renamed.

**Relationship identity** is `MemoryEdge.edge_id` (unchanged). The same
preservation rule applies. Relationships never merge (confirmed: §5.1 of
ADR-027 defines no restore/merge/reclassify operation for relationships),
so relationship identity is the simpler, non-fan-in case of the same rule.

**Rationale:** preserving identity avoids introducing a compound key
(`entity_id` + `version`) into `MemoryGraph`'s existing one-entry-per-id,
dict-keyed structure — the smallest change consistent with §6's
constraints, and consistent with how `build_revision` already treats a
`node_id` as the stable unit of replacement across revisions.

### 9.1 Ownership

**`MemoryNode` gains a new field: `owner: SafeLabel`**, required (no
default — every `MemoryNode` already has a server-assigned owner at
construction via `Entity.owner`, so a default would silently mask a missing
value rather than surface it). This resolves a gap identified during
independent review: ADR-027 §5.2's ownership-override authorization check
reads "the recorded owner" from the object being mutated, and `MemoryNode`
— the object actually read at mutation time — has no owner field today
(confirmed, §5), an omission of exactly the same shape as the
`lifecycle_status`/`supersedes` gaps this ADR already closes.

**This document owns the decision to add the field; ADR-027 owns how
authorization consumes it.** `owner` is included here, not as a new
identity/lifecycle/supersession concept in its own right, but because it is
the same class of problem as §10/§11's additions: a value `Entity` already
carries, lost by `MemoryNode.from_entity()`, needed by a mutation operation
this ADR exists to unblock. Adding it alongside `lifecycle_status`/
`supersedes` in one additive `MemoryNode` change is smaller than a second,
separate ADR for one field, and keeps every lossy-conversion fix in one
place. This ADR does not define, change, or interpret the ownership-override
authorization rule itself (§5.2's comparison logic, the `knowledge-steward`
override, or the service-caller restriction) — that remains entirely
ADR-027's decision and is unmodified here.

`owner` is preserved unchanged by every lifecycle-class replacement in §12
(Merge is the only operation that could plausibly change it, and does not —
the survivor's own existing `owner` is retained, never inherited from a
source).

### 9.2 Relationship identity: endpoint changes, reassignment, and collisions

**Endpoints (`source_id`/`target_id`) are immutable for the lifetime of an
`edge_id`.** Update Relationship (§5.1 of ADR-027) may change a
relationship's non-endpoint fields (e.g. classification) but never its
endpoints — `edge_id` is never re-derived from new endpoint values under
Update. A caller needing to represent "this relationship now points
elsewhere" does so by closing the existing edge's validity (§14) and
issuing a separate Create Relationship for the new endpoint pair — a new
`edge_id`, not a reassignment of the old one. This is the same pattern
`edges.py`'s own docstring already describes for any relationship change
("adding a new edge and closing the old one's validity ... never mutating
in place"), applied consistently rather than only to the ordinary ingestion
case.

**Merge's edge reassignment (§12 step 5) is the one place an endpoint
genuinely changes**, and is handled identically: the source-endpoint edge
is closed (validity ended, `edge_id` unchanged, now non-live), and a
**new** `MemoryEdge` is constructed with the survivor substituted for the
source endpoint — via the same `edge_id` derivation Create Relationship
already uses (an explicit `relationship_id` where the caller supplies one,
`edge_id_for(edge_type, source, target)` otherwise). The old and new edges
are two distinct identities; the old `edge_id` is never reused for the new
endpoint pair.

**Collision handling:** if the newly-constructed post-merge edge's
`edge_id` collides with an already-existing, currently-live edge for the
same `(edge_type, survivor_id, target_id)` combination, this is an ordinary
duplicate-relationship conflict, resolved by the same conformance
validation Create Relationship already performs before construction — a
command-shape/conflict validation failure (ADR-027 §15.1), never a silent
overwrite and never routed through `_validate_edge_group`'s
immutable-fields check (which the new construction path bypasses entirely,
per §8's decision).

## 10. Lifecycle Model

**Canonical enum:** `emg_knowledge_lifecycle.states.VersionState` (six
values: `PROPOSED`, `ACTIVE`, `DEPRECATED`, `SUPERSEDED`, `ARCHIVED`,
`RETIRED`), reused unchanged — no new enum, no modification to
`_TRANSITIONS`/`is_valid_transition`/`LIVE_STATES`.

**New field:** `MemoryNode.lifecycle_status: VersionState =
VersionState.ACTIVE` — additive, defaulted, so every existing construction
call site and every historical persisted `MemoryNode` (deserialized without
this key present) remains valid.

**Transition enforcement:** every lifecycle-changing operation calls the
existing `is_valid_transition(current, target)` before constructing a
replacement `MemoryNode`; an invalid transition is rejected before any
`GraphStore.transaction()` opens — no new validation logic, the existing
pure function is authoritative.

`emg_ontology.LifecycleStatus` is **not** extended, reconciled, or mapped
in code. Its four values and two-call-site, always-`.ACTIVE` usage in
`emg-knowledge-pipeline` continue exactly as today. The states.py docstring
alignment table remains documentation of a historical intent, not a runtime
contract this ADR implements — reconciling it would touch a type this
ADR's confirmed evidence shows has no operative need to change.

`MemoryEdge` gains **no** lifecycle field — relationship "liveness" remains
governed entirely by `TemporalValidity` (§12), a different, already-correct
axis (temporal truth, not administrative state).

### 10.1 Reachability of `VersionState`'s six values

Independent review correctly flagged that not every `VersionState` value is
reachable by an operation this ADR or ADR-027 defines. Rather than narrow
the enum (which would mean not fully reusing `VersionState`, reopening §8's
decision) or silently accept unreachable values (repeating the exact
`LifecycleStatus` pattern this ADR exists to fix), the reachable subset is
stated explicitly here as this ADR's own contract, without changing
`_TRANSITIONS`/`is_valid_transition`/`LIVE_STATES` in `emg-knowledge-lifecycle`:

| State | Reachable via | Status |
| --- | --- | --- |
| `ACTIVE` | Create Entity (commits directly here, §9.2 of ADR-027) | **Reachable today.** |
| `SUPERSEDED` | Retire (`ACTIVE→SUPERSEDED`), Restore (`ARCHIVED→SUPERSEDED`), Merge sources (§12 step 4) | **Reachable today.** |
| `ARCHIVED` | No operation this ADR or ADR-027 defines transitions a node *into* `ARCHIVED` (the legal predecessor transitions are `SUPERSEDED→ARCHIVED`/`RETIRED→ARCHIVED`, neither produced by any defined operation). | **Reachable only via a future, external mechanism** (e.g. a retention/archival process) — consistent with `emg-knowledge-lifecycle`'s own `evaluate_archive`/`ArchiveDecision` being explicitly "decision support only... does not enforce, schedule, or persist." Restore therefore currently has no operation-produced input to act on; this is a disclosed, honest gap, not silently hidden — see Risks (§17). |
| `PROPOSED` | None. Reserved for a future authoring/review workflow (Module 7's Knowledge Authoring UI), per ADR-027 §9.2's own prior framing. | **Not reachable, reserved.** |
| `DEPRECATED` | None. No operation this ADR or ADR-027 defines produces it; ADR-027 §9.2 explicitly routes Delete `ACTIVE→SUPERSEDED` directly, bypassing it by design. | **Not reachable, reserved** — kept in the enum because it is part of `VersionState` as reused unmodified (§8), not because a current consumer needs it; a future authoring/review or moderation workflow is the anticipated eventual consumer. |
| `RETIRED` | None. Legal from `PROPOSED`/`DEPRECATED`/`SUPERSEDED`, but no currently-defined operation performs any of those transitions. | **Not reachable, reserved** — same status as `DEPRECATED`. |

This table is this ADR's answer to "why the complete enum remains
canonical": `VersionState` is reused **unmodified** because narrowing it
would itself be a second, smaller version of the exact reconciliation
problem (§4) this ADR exists to avoid reproducing, and because three of the
six values have a clearly identified, plausible future consumer (the
reserved authoring/moderation workflow, and archival) rather than being
speculative. The table's role is to make today's actual reachability
explicit and auditable, not to pretend the whole enum is exercised now.

### 10.2 Terminology: "Restore Entity" vs. "Restore Revision"

Two distinct, unrelated operations share the word "restore" across this
ADR's lineage of documents, and neither ADR-023 nor ADR-027 previously
cross-referenced the other's use of the term:

| | **Restore Entity** (this ADR / ADR-027 §9.3) | **Restore Revision** (ADR-023 §8 item 5, `RestoreRevisionCommand`) |
| --- | --- | --- |
| Scope | One `MemoryNode`, by `node_id` | The entire tenant graph, one whole historical `MemoryGraph` snapshot |
| Mechanism | Lifecycle transition, `ARCHIVED→SUPERSEDED`, via this ADR's new construction path | Staging a historical snapshot unmodified through the existing `GraphStore.transaction()`, per ADR-023 §8 item 5 |
| Resulting state | The single entity becomes `SUPERSEDED` — non-live, not reinstated as current | The whole tenant graph's current state becomes the restored snapshot's content — fully live |
| Governing document | This ADR (mechanism) / ADR-027 (operation, authorization) | ADR-023 (unchanged, not touched by this ADR) |

Future documentation and implementation should say "Restore Entity" and
"Restore Revision" (or "Revision Restore," matching `RestoreRevisionCommand`'s
existing name) explicitly wherever either could be ambiguous, rather than
the bare word "restore." No existing command, type, or ADR-023 content is
renamed by this note — it is a disambiguation, not a redesign.

## 11. Supersession Model

**New field:** `MemoryNode.supersedes: tuple[SafeLabel, ...] = ()` —
forward-only, populated only at construction of the new/surviving object,
empty for every ordinary (non-merge) lifecycle change.

**`superseded_by` is never stored.** No field is added to `MemoryNode` or
`MemoryEdge` for it. It is derivable, when needed, by a pure, read-only
query (`superseded_by_for(graph: MemoryGraph, node_id: str) -> str | None`,
or a tuple if more than one — a new, additive function in `emg-memory-graph`,
not a stored field) that scans current `supersedes` tuples for a match.
This mirrors the pattern `VersionChain.lineage()` already uses correctly
(derive ancestry from forward pointers on the newer object; never write
back onto an older, frozen one) and matches the ontology's own dead field
as evidence this was the intended shape all along, simply never
implemented.

`MemoryEdge` gains no supersession field — an edge is never superseded by
another edge under this model; a changed relationship is represented by
closing the old edge's validity (§12/§14) and, where the endpoint itself
changes (Merge), constructing a new edge — no edge-level `supersedes`
concept is needed.

### 11.1 Integrity invariants

Four invariants, stated explicitly per independent review, none requiring a
new stored field or a change to `_TRANSITIONS`:

1. **Uniqueness.** A given `node_id` may appear in the `supersedes` tuple
   of **at most one** other `MemoryNode` at any time. `supersedes` is
   populated only by Merge (§12), and only for source ids being absorbed
   into exactly one survivor in that one operation — two different
   survivors independently claiming to have absorbed the same source id is
   a contradiction the construction path must reject.
2. **Cycle prevention — derived, not separately enforced.** No new
   cycle-detection algorithm is introduced (that would duplicate
   `VersionChain`'s own machinery, contrary to §6's "reuse, never
   reimplement" constraint). Instead, cycles are prevented **by
   construction**, from the combination of invariant 1 and invariant 3
   below: a node can only ever appear in `supersedes` while still live
   (invariant 3), and once absorbed it becomes `SUPERSEDED` (non-live) and,
   by invariant 1, can never be absorbed again nor become a survivor of a
   later merge (§12.3 below). The `supersedes` relation is therefore
   a forest of forward pointers from currently-or-formerly-live nodes to
   now-non-live ones, never a graph with a path back to itself.
3. **Only a live node may be a survivor or a source.** A node whose
   `lifecycle_status` is not in `emg_knowledge_lifecycle.states.LIVE_STATES`
   at the time of merge (i.e. not `PROPOSED`/`ACTIVE`/`DEPRECATED`) may not
   be selected as either a survivor or a source. This is the same rule
   §12.3 states for the archived-source case, generalized: it is what makes
   invariant 2's cycle-freedom argument hold, not a separate, ad hoc
   restriction.
4. **Orphan prevention.** Every id placed in a survivor's `supersedes`
   tuple must resolve to a `MemoryNode` present in the `MemoryGraph`
   snapshot the merge operation read at transaction start. Because Merge's
   construction path only ever reads source ids from that already-read
   snapshot (§12), an unresolvable source id cannot silently enter
   `supersedes` — presenting one is a validation failure, rejected before
   any transaction opens, using the same `InvalidMutationCommandError`
   shape ADR-027 §15.1 already defines for command-shape failures.

**Validation responsibility:** all four invariants are enforced inside the
new `MemoryGraphBuilder` construction path (§13), at the same layer
`_validate_edge_group` already validates immutable-fields conflicts for the
existing merge path — not pushed up to the application/command layer and
not left to `GraphStore`. This keeps validation co-located with the
construction logic it constrains, consistent with where equivalent checks
already live in this package today.

### 11.2 Growth bound

`supersedes` is **not unbounded**. A fixed, code-level ceiling
(`MAX_SUPERSEDES`, exact numeric value an implementation detail) must exist,
following the same "architectural ceiling, not runtime configuration"
convention this platform already applies everywhere else a collection field
exists (`MAX_ALIASES`, `MAX_EVIDENCE_REFS`, `MAX_ATTRIBUTES`, and ADR-027
§12's own operational-constraints table). Leaving `supersedes` unbounded
would be the one collection field in this codebase without a ceiling — an
unjustified, inconsistent exception, not a deliberate design choice. A
merge absorbing more sources than the ceiling allows in one operation is
performed as multiple sequential merges, each producing its own revision —
mirroring how ADR-027 §11 already handles "batch too large" by capping
batch size rather than by permitting unbounded batches, not a new pattern.

## 12. Merge Model

Merge is the many-to-one case of §11's supersession mechanism, not a
separate concept, and is explicitly decoupled from `EntityResolver` (which
remains, at most, an upstream mention-clustering aid during ingestion, never
the merge executor):

Given a survivor `node_id` and one or more source `node_id`s, all already
present in the just-read `MemoryGraph`:

0. **Eligibility (§11.1 invariant 3):** every source, and the survivor
   itself, must currently be in a `LIVE_STATES` state
   (`PROPOSED`/`ACTIVE`/`DEPRECATED`). Any source or survivor not in a live
   state — including `ARCHIVED` (§12.3 below) — fails eligibility before
   any other step runs.
1. Compute survivor classification as the maximum across survivor and every
   source, using ADR-026 Amendment 1's existing dominance ordering (policy
   data, no new comparator).
2. Union evidence across survivor and every source via the existing,
   unmodified `_merge_evidence` pure function.
3. Combine every other field-level, per §12.1: aliases, histories,
   metadata, and label, reusing `_merge_node`'s existing combining rules
   rather than inventing new ones.
4. Construct the replacement survivor `MemoryNode`: same `node_id`,
   `supersedes = tuple(source_node_ids)`, `classification` = the step 1
   maximum, `evidence`/`aliases`/`histories`/`metadata`/`label` = §12.1's
   results.
5. For each source: validate `is_valid_transition(current, SUPERSEDED)`
   (satisfied automatically given step 0's eligibility check — every live
   state has a legal path to `SUPERSEDED`), construct a replacement
   `MemoryNode` with `lifecycle_status=SUPERSEDED` — the source's own
   `node_id` and all other content are otherwise preserved, never deleted
   or renamed.
6. For every `MemoryEdge` with a source `node_id` as an endpoint (found via
   the current graph, not `active_edges_at` alone): close its validity
   (§9.2/§14) **and** construct a new `MemoryEdge` with the survivor's
   `node_id` substituted for the source endpoint, per §9.2's edge
   reassignment and collision rules.
7. Stage every replacement (survivor, sources, closed edges, new edges)
   together; commit as one revision (§12.2).

### 12.1 Field-level merge specification (aliases, metadata, histories, label)

Left unspecified in Revision 1; specified explicitly here, in every case by
**reusing `_merge_node`'s existing, already-correct combining rule** for
that field — applied to the survivor's and sources' already-persisted
`MemoryNode` objects rather than to freshly-ingested `NodeInput` objects
(Merge operates on entities already in the graph, not new ingestion input;
only the entry point differs, not the combining semantics):

- **Aliases:** unioned across survivor and every source — the same
  set-union, sorted-output rule `_merge_node` already applies
  (`aliases.update(...)`, deduplicated, sorted).
- **Histories:** combined by attribute, the survivor's own existing history
  for a given attribute taking precedence over any source's on a name
  collision; a source's history for an attribute the survivor does not
  already have is added — the same per-attribute, deterministic collapsing
  rule `_merge_node` already applies (`histories[h.attribute] = h`), with
  the survivor treated as authoritative because it is the entity moving
  forward, not a new merge policy invented for this case.
- **Metadata:** unioned via the existing, unmodified `_merge_metadata` pure
  function — survivor's items plus every source's items, collapsed by key.
- **Label:** the survivor's own existing label is preserved unchanged,
  never overwritten by a source's label — the same rule `_merge_node`
  already applies to an existing node during ordinary ingestion
  (`existing.label if existing is not None else rep.label`); a merge does
  not change what the survivor is called.

No new field-combining algorithm is introduced by Merge; every rule above
is `_merge_node`'s existing behavior, invoked for a different input shape.

### 12.2 Atomicity and rollback

Merge introduces **no new atomicity mechanism**. It inherits ADR-027's
existing guarantees in full: the transaction's own context-manager
semantics (ADR-027 §15.4/§15.6) mean that if step 0's eligibility check, any
of steps 1–6's construction steps, or §11.1's integrity invariants fail for
any source, **no** `GraphStore.transaction()` is opened, or if already
open, nothing is staged — identical in kind to how ADR-027 §11.3 already
requires a batch to abort entirely on any single item's failure, with zero
committed changes and no partial merge ever observable. A merge is either
one complete revision (survivor replaced, every source replaced, every
incident edge closed and reassigned) or no revision at all — never a subset.
This ADR does not modify ADR-027 §10 (concurrency) or §11 (batch atomicity);
Merge is simply one more caller of the same, unchanged mechanism.

### 12.3 Archived sources are forbidden, not merged or transformed

Independent review flagged that merging an `ARCHIVED` source is ambiguous,
because `ARCHIVED→SUPERSEDED` is also Restore's own transition (§9.3 of
ADR-027) — nothing would distinguish, after the fact, whether a source's
resulting `SUPERSEDED` state came from being merged or being restored.

**Resolved: forbidden, not allowed or transformed.** §12 step 0's
eligibility check excludes any node not in `LIVE_STATES` — `ARCHIVED` is
not a live state, so an `ARCHIVED` node may never be a Merge source or
survivor. This is not an arbitrary restriction; it is the same rule
(§11.1 invariant 3) that makes cycle-freedom hold for `supersedes`, applied
consistently rather than special-cased for this one ambiguity.

**How this differs from Restore, and the resulting path for an archived
entity a caller wants to merge:** Restore (§10.2) is the only operation
that ever transitions a node *out of* `ARCHIVED`, and its own result is
`SUPERSEDED` — itself not a live state. Per ADR-027 §9.3's own existing
rule, a caller wanting restored content to become live again "must follow
the restore with a separate, independently-authorized Create/Update
mutation" — only after that subsequent operation produces a live entity
does it become eligible as a Merge participant. Merge therefore never
touches `ARCHIVED` content directly, by construction, and the two
operations' outcomes remain unambiguous: a node in `SUPERSEDED` state was
either (a) restored and not yet reinstated, (b) retired, or (c) absorbed by
a merge — distinguishable, when needed, by checking whether any other
node's `supersedes` tuple references it (case c) — never conflated with (a)
or (b), since neither of those ever populates any `supersedes` tuple.

## 13. MemoryGraph Implications

- `MemoryNode` gains three fields: `lifecycle_status: VersionState =
  VersionState.ACTIVE`, `supersedes: tuple[SafeLabel, ...] = ()` (bounded
  by the new `MAX_SUPERSEDES` ceiling, §11.2), and `owner: SafeLabel`
  (required, no default — §9.1; see §14 for how this interacts with
  backward compatibility). No other field changes.
- `MemoryEdge` gains **no** new field — `TemporalValidity.valid_until`
  already exists and is sufficient; the gap was construction, not schema.
- `MemoryGraphBuilder` gains one new construction entry point (exact name
  TBD at implementation time — e.g. a `replace`/`mutate` method) alongside
  the existing `build`/`extend`/`from_ontology`, performing single-object
  substitution without invoking `_merge_node`/`_merge_edge`/
  `_validate_edge_group`, and enforcing §11.1's four integrity invariants
  and §11.2's `MAX_SUPERSEDES` ceiling. The existing three methods and
  their exact current behavior are **unchanged** — this is a new, parallel
  path, not a modification of the existing one.
- `MemoryGraph`'s own structure (an immutable tuple of nodes, an immutable
  tuple of edges, exactly one live entry per id) is unchanged. Historical/
  superseded content does not need to coexist with current content in one
  snapshot — the append-only revision log (ADR-022/023) already retains
  every past snapshot, so no second history mechanism is introduced inside
  `MemoryGraph` itself.
- A new, additive, read-only query function (`superseded_by_for` or
  equivalent) is added for deriving §11's non-stored back-reference.

## 14. Compatibility Analysis

- Every existing `MemoryNode`/`MemoryEdge` construction call site
  (`from_entity`, `from_relationship`, `from_ontology`, `build_revision`)
  is unaffected in practice, though the three new fields split into two
  different compatibility categories, not one uniform one as Revision 1
  stated:
  - `lifecycle_status` and `supersedes` carry ordinary pydantic defaults
    (`VersionState.ACTIVE` and `()` respectively) for **both** purposes a
    default can serve here: existing construction call sites need no
    change, and historical `graph_revisions.graph_json` rows (persisted
    without these keys) deserialize correctly.
  - `owner` is **architecturally required with no default for any new
    write** (§9.1) — but still needs *some* technical deserialization
    behavior for the two cases above, and those two cases are handled
    differently, not conflated:
    - **Historical `graph_revisions.graph_json` rows** predating this
      field: `owner` is given a pydantic-level default solely for
      deserialization safety (e.g. an empty-string `SafeLabel` sentinel),
      so reading old revisions never fails. This default exists only to
      keep historical data readable — it is not an endorsement of an
      empty owner for any node going forward.
    - **Every new construction call site** (`from_entity`, the new
      replace-path in `MemoryGraphBuilder`): `owner` must be supplied from
      `Entity.owner`, which is itself already required/non-optional at the
      ontology layer (§5), so `from_entity()`-based construction is
      unaffected in practice — there is no existing call site that has an
      `Entity` without an owner to draw from. The empty-sentinel default is
      never exercised by a real construction path; it exists purely for
      historical-row deserialization. This is an architectural rule
      enforced by the new construction path's own validation (§11.1's
      "Validation responsibility" pattern), not a claim that the type
      system alone prevents an empty owner — consistent with how this ADR
      elsewhere states invariants are enforced at the construction layer,
      not assumed from field typing.
  - With this distinction stated explicitly, existing tests/fixtures that
    do not reference `owner` continue to validate unchanged (they exercise
    `from_entity()`-based paths, where `Entity.owner` already supplies a
    value), and no historical row fails to deserialize.
- `_merge_node`/`_merge_edge`/`_validate_edge_group`/`_edge_immutable_fields`
  are **not modified** — `build_revision`'s existing behavior, already
  relied upon in production and by existing tests, is fully preserved. The
  new replace-path is additive and parallel, never a change to the existing
  one.
- No `frozen=True` contract is relaxed anywhere; no mutation method is
  added to any existing class.
- `GraphStore`/`GraphTransaction`/`WriteReceipt` (`emg_platform_core.ports.graph_store`)
  — zero changes; this ADR only changes what content is constructed before
  `stage()`/commit, never the write substrate.
- Query Engine (ADR-024) — unaffected by this ADR; how it should
  incorporate the new `lifecycle_status` field into read-path visibility is
  explicitly deferred (§18), matching this ADR's non-goal boundary.

## 15. Migration Impact

- **No database migration.** `MemoryNode`/`MemoryEdge` are serialized as
  `jsonb` inside `graph_revisions.graph_json`; the three new fields
  (`lifecycle_status`, `supersedes`, `owner`) each carry a pydantic-level
  default sufficient for deserialization (§14 distinguishes `owner`'s
  deserialization-only default from its no-default rule for new writes),
  so every historical row deserializes correctly without a schema change.
- `MAX_SUPERSEDES` (§11.2) is a new, additive code-level constant in
  `emg-memory-graph` — no configuration, migration, or schema impact.
- **No new dependency edge required.** `libs/python/emg-memory-graph/pyproject.toml`
  **already declares** `emg-knowledge-lifecycle` as a dependency (confirmed,
  §5) — it is simply not yet imported anywhere in `emg-memory-graph`'s
  source. Implementing this ADR's decision means consuming an
  already-declared, already-governance-clean edge, not adding one; no
  `docker/dependencies.yaml` or manifest change is required.
- `libs/python/emg-ontology`, `libs/python/emg-platform-core`,
  `libs/python/emg-persistence`, `GraphStore`'s Protocol, and CI governance
  scripts themselves — **no change**.
- Implementation (not authorized by this document — this is an
  architecture-only ADR) would touch only `libs/python/emg-memory-graph`:
  `nodes.py` (two new fields), `builder.py` (one new method), a new
  query-function module or addition to `temporal_query.py`, and that
  package's own test suite.

## 16. Consequences

**Positive:** ADR-027 Revision 3 can cite one real, implemented-or-
implementable mechanism for §9 (soft delete), §9.5 (relationship closure),
and §5.1/§9.2 (Merge) instead of a nonexistent one. The Query Engine and any
future consumer of `MemoryGraph` (Search/GraphRAG, a future authoring
workflow) inherit a well-defined lifecycle/supersession concept without a
separate design effort. `emg-knowledge-lifecycle`'s `VersionState`/
`is_valid_transition` — built, tested, and previously unconsumed — become
genuinely used, closing the exact gap ADR-027 §3.2 already flagged
("not wired to the ontology or any store").

**Negative:** `emg-memory-graph`, a foundational, multi-consumer package,
gains three new `MemoryNode` fields (`lifecycle_status`, `supersedes`,
`owner`), one new construction method, one new query function
(`superseded_by_for`), and one new constant (`MAX_SUPERSEDES`) — a real,
disclosed increase in its surface area. Every future `MemoryNode`/
`MemoryEdge` consumer must be aware these fields exist, even one whose use
case ignores them, and `owner`'s no-default-for-new-writes rule (§9.1/§14)
is an additional, real constraint any future construction path must
satisfy explicitly rather than inherit for free.

## 17. Risks

- **`superseded_by`-as-derived may need materialization at scale.** A
  linear scan over `supersedes` tuples is correct and sufficient for the
  volumes this ADR's evidence covers; if a future read pattern demands
  frequent "what superseded this?" lookups at high volume, an index or
  cached projection may be needed — explicitly deferred (§18), not designed
  here.
- **Edge reassignment on Merge changes `edge_id` stability.** §12 step 6
  means a caller who cached or referenced an edge's id across a merge event
  will find the old id closed (non-live) and a new id representing the
  post-merge relationship — now formally specified, including collision
  handling, in §9.2, rather than left an open risk as in Revision 1. Still
  worth flagging plainly here as a real, disclosed behavior any future
  consumer must account for, not a defect.
- **`ARCHIVED` is currently unreachable by any defined operation.** §10.1
  discloses that no operation this ADR or ADR-027 defines transitions a
  node into `ARCHIVED`, so Restore (`ARCHIVED→SUPERSEDED`) currently has no
  operation-produced input to act on. This is an honest, stated gap, not a
  design flaw — `ARCHIVED` entry is explicitly the responsibility of a
  future, external retention/archival mechanism (consistent with
  `emg-knowledge-lifecycle`'s own `evaluate_archive` being
  "decision support only"), out of scope for this ADR and for ADR-027
  Revision 3.
- **`owner`'s historical-row deserialization default is a distinct concept
  from its no-default-for-new-writes rule** (§14). Any future code touching
  `MemoryNode` construction must preserve this distinction deliberately —
  a maintainer who naively reuses the deserialization default as a
  "convenient" default for new construction would silently reintroduce the
  authorization gap this ADR closes.
- **Alternative B (full `VersionChain` adoption) remains available and
  possibly superior** if a future need for its cycle/orphan-detection
  guarantees emerges across many concurrent merges — choosing the narrower
  path now is a deliberate scoping decision (§7), not a permanent
  foreclosure, and should be revisited if that need materializes.
- **This is the third prerequisite-shaped document in this ADR-027
  investigation chain.** A legitimate outcome of rigorous review, but
  worth naming plainly rather than treating each finding as an isolated
  surprise, consistent with this session's own prior risk notes.

## 18. Deferred Decisions

- **Query-layer visibility** — how `services/knowledge-graph`'s existing
  read methods incorporate `lifecycle_status`/`LIVE_STATES` filtering
  (the confirmed §7-of-ADR-027 Non-Goals contradiction) is explicitly
  ADR-027 Revision 3's job, not this ADR's — this ADR only fixes what
  "current" and "historical" mean structurally on `MemoryNode`.
- **Whether `VersionChain`'s full machinery (Alternative B) should
  eventually replace the narrower `supersedes`-tuple approach** — left
  open, not adopted now.
- **`superseded_by` materialization/indexing**, if usage patterns demand it
  beyond a linear scan.
- **Any authorization, idempotency, concurrency, or HTTP-layer consequence**
  of this model — entirely ADR-027's scope, untouched here.
- **A future `PROPOSED`-state authoring/review workflow** — still reserved,
  unbuilt, per ADR-027 §9.2's own prior framing, unchanged by this ADR.
- **Physical erasure** — remains out of scope repository-wide (ADR-027
  §9.4, unchanged).
- **`emg-entity-resolution` ownership (D-A-002)** — unrelated, untouched.

---

**No code has been written or modified to produce this document. No
existing ADR was updated. Implementation of this decision, and the
corresponding revision of ADR-027, are both future, separately-approved
steps.**
