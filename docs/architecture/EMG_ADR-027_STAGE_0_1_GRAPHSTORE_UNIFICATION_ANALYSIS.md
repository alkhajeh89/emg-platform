# ADR-027 Stage 0.1 — GraphStore Protocol Unification: Stop-and-Analyze

**Historical Status:**
- This document reflects the pre-implementation assessment.
- Its blocking conditions were subsequently resolved or formally deferred.
- It is retained for architectural traceability.
- It is not an active implementation directive.

**Status:** Blocking analysis — implementation paused pending approval.
**Governing document:** `docs/architecture/PROMPT_TEMPLATE_POST_ADR026.md`;
`docs/architecture/EMG_ADR-027_KNOWLEDGE_GRAPH_MUTATION_API.md` (Revision 2, §4,
§17).
**Trigger:** Stage 0.1 ("GraphStore Protocol unification") was found, during
implementation, to require a larger refactor and a genuine architectural
decision than ADR-027 Revision 2's Repository Impact section (§17) anticipated.
Per the explicit instruction governing this session, work stopped before any
`emg-knowledge-pipeline` source file was modified.

No production code in `emg-knowledge-pipeline` has been changed by this
analysis. Stage 0.2 (role catalog) and Stage 0.3 (idempotency migration) are
implemented, validated, and unaffected by this stop.
... (rest of file) ...
---

## Closing Note

**Historical Outcome:** The GraphStore Protocol unification was formally deferred out of ADR-027's mandatory implementation gate. ADR-027 implementation proceeded successfully using the existing Protocol, and subsequent stages (1 and 3) were implemented without this unification. This analysis is preserved for historical context regarding the deferred architectural decision.
---

## 1. Architecture Review

ADR-027 Revision 2 §4 decided to **Replace** the duplicate `GraphStore`
Protocol in `libs/python/emg-knowledge-pipeline` with the platform-wide,
Freeze-§32-named `GraphStore` Protocol in `emg_platform_core.ports.graph_store`,
treating this as a Stage 0 prerequisite so no new mutation code is ever written
against the wrong abstraction.

Both Protocols are named `GraphStore`, but they are not the same shape of
contract — they operate at different grains entirely:

| | `emg_knowledge_pipeline.graph_store.GraphStore` | `emg_platform_core.ports.graph_store.GraphStore` |
|---|---|---|
| Unit of write | One `Entity` / `Relationship` at a time (`add_entity`, `add_relationship`) | One whole `MemoryGraph` snapshot (`write(tenant, graph, principal=)`) |
| Read shape | Point lookup by id (`get_entity(id)`, `get_relationship(id)`) | Whole-graph snapshot (`read(tenant)`) |
| Tenancy | None — no `tenant` parameter anywhere in the Protocol | Every method takes `tenant: TenantId` |
| Conflict semantics | Per-object `existing.model_dump() == built.model_dump()` equality, checked by the caller (`validation.py`) before commit | None at this grain — a `write`/`stage` replaces the tenant's entire snapshot; no per-node compare-and-skip exists in the Protocol |
| Concurrency control | A process-local `threading.Lock` inside `InMemoryGraphStore._apply` | `graph_revisions` PK `(tenant_id, revision_number)` — a storage-layer CAS (per ADR-027 §10) |

This is not a signature difference that a thin adapter shim can absorb. The
knowledge-pipeline's entire validation/idempotency design (`validation.py`
§below) is written against an **incremental, per-object** store; the
platform-core Protocol is a **whole-snapshot, tenant-scoped** store. Adapting
one to the other means changing what "idempotent re-ingestion" and "conflict"
*mean*, not just changing which class implements an interface.

## 2. Root Cause Analysis

ADR-027 Revision 2 §17 (Repository Impact) characterized this as removing a
duplicate Protocol and pointing the pipeline at the existing one. That framing
undersold two concrete gaps found while attempting the change:

1. **No tenant concept in ingestion.** `IngestionContext`
   (`libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/context.py`,
   lines 47–67) carries `source_principal`, `source_type`, `owner`,
   `correlation_id`, `ingest_time`, `trust_score` — no `tenant`/`TenantId`
   field at all. The unified `GraphStore.read`/`write`/`transaction` all
   require a `tenant: TenantId` as their first argument (`ports/graph_store.py`
   lines 118, 122–124, 133–135). There is no tenant to pass without first
   deciding where it comes from (a new required `IngestionContext.tenant`
   field? Derived from `source_principal`? From a new caller-supplied
   parameter?) — none of which ADR-027 specifies.

2. **Per-object idempotency/conflict detection cannot be carried over
   unchanged.** `validate_and_build`
   (`libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/validation.py`,
   lines 251–265 for entities, 338–349 for relationships) does:
   ```python
   existing = store.get_entity(entity_id)
   if existing is not None:
       if existing.model_dump() == built.model_dump():
           result.skipped_entity_ids.append(entity_id)  # idempotent no-op
       else:
           raise ...  # conflict — reject
   ```
   This requires a point lookup that returns the **original `Entity`**, so a
   full-fidelity equality comparison is possible. The unified store has no
   `get_entity(id)` — only whole-graph `read(tenant)`. Even reading the whole
   graph and finding the node by id, the node is a `MemoryNode`
   (`emg_memory_graph.nodes.MemoryNode`), not an `Entity`.
   `MemoryNode.from_entity()`
   (`libs/python/emg-memory-graph/src/emg_memory_graph/nodes.py`, lines
   88–117) is a **lossy** projection: it keeps `entity_id`, `entity_type`,
   `classification`, `trust_score` (as `confidence`), `provenance_reference`
   (folded into `source`), and `effective_from` (as `created_at`) — it does
   **not** retain `owner`, `lifecycle_status`, `version`, `effective_to`,
   `supersedes`/`superseded_by`, or any of the entity's domain-specific
   attributes (the `**domain_attrs` merged into `_build_entity`,
   `validation.py` lines 106–124). A `MemoryNode` cannot be converted back
   into an `Entity` and compared byte-for-byte, so `existing.model_dump() ==
   built.model_dump()` cannot be reproduced faithfully once storage is a
   `MemoryNode`. **Unifying the store silently changes what "idempotent
   re-ingestion" and "conflict" mean** — a behavior change, not a
   refactor-preserving swap.

Both gaps stem from the same underlying fact: the two `GraphStore`s were
built for different jobs (incremental ontology ingestion vs. whole-graph
tenant-scoped mutation) and happen to share a name. ADR-027's "Replace"
decision is very likely still the right end-state call — having two
`GraphStore` Protocols in one repository is a real architecture-fitness
problem — but the *mechanism* of replacement needs its own explicit design,
not an implicit "swap the import."

## 3. Proposed Refactoring Plan

Two independently workable strategies; either resolves the gap, but they trade
off differently, so this is presented as a choice rather than a
recommendation-with-no-alternative (see §7).

**Strategy A — Redefine ingestion idempotency at the graph level, accept the
behavior change.**
1. Add `tenant: TenantId` to `IngestionContext` (a new required field —
   `frozen=True, extra="forbid"` already on the model, so this is an additive,
   explicit schema change, not a silent one).
2. Replace `GraphStore`/`GraphTransaction` imports in `pipeline.py`,
   `validation.py`, `resolver.py` (where applicable) with
   `emg_platform_core.ports.graph_store.GraphStore`.
3. Rewrite `validate_and_build`'s idempotent-skip/conflict logic: read the
   tenant's current `MemoryGraph` once per batch, look up existing nodes/edges
   by id, and redefine "conflict" as a documented, narrower comparison over
   only the fields `MemoryNode`/`MemoryEdge` actually retain (id, type,
   classification, confidence, source) rather than full `Entity` equality.
   This must be written up as an explicit, reviewed change to FEAT-05-2's
   idempotency contract, not silently narrowed.
4. Replace `InMemoryGraphTransaction`/`InMemoryGraphStore` usage with the
   platform-core adapter; delete the duplicate Protocol and its
   implementation from `emg-knowledge-pipeline` entirely.
5. Update `emg-knowledge-pipeline`'s `pyproject.toml` to depend on
   `emg-platform-core` (and transitively `emg-memory-graph`), which it does
   not today (confirmed: its declared deps are only `emg-common-types`,
   `emg-errors`, `emg-ontology`, `emg-audit-client`).

**Strategy B — Treat the store swap as its own follow-on ADR-027 stage
(defer, don't fold into Stage 0).**
1. Leave `emg-knowledge-pipeline`'s existing `GraphStore` Protocol and
   `InMemoryGraphStore` exactly as they are for now.
2. Close Stage 0 on the two items actually delivered (role catalog,
   idempotency migration) plus a documented, explicit decision that
   "duplicate GraphStore Protocol removal" is deferred to a new stage (call
   it Stage 0.1-revised or fold it into Stage 2, whichever the reviewer
   prefers) with its own design write-up covering exactly the idempotency
   semantics change in §3(A).3 above, reviewed on its own before any code
   changes.
3. Add an interim architecture-fitness test asserting the *intent* (only one
   `GraphStore` Protocol should exist long-term) as a tracked, currently-xfail
   or skip-with-reason test, so the duplication is a visible, tracked debt
   item rather than a silent gap.

## 4. Dependency Impact

- **Strategy A** adds a new edge: `emg-knowledge-pipeline` → `emg-platform-core`
  → `emg-memory-graph`. This is consistent with the repository's `services/*`
  → `libs/python/*` dependency direction rule (both are `libs/python/*`
  packages; the ADR-026/027 precedent already has `libs/python` packages
  depend on other `libs/python` packages, e.g. `emg-knowledge-graph` service
  depending on `emg-platform-core`), but it is a **new** dependency that must
  be added to `pyproject.toml`, the dependency manifest
  (`tools/ci/check_dependency_manifest.py`'s source of truth), and verified by
  `check_dependency_drift.py`/`check_implicit_dependencies.py` — none of which
  currently declare or expect this edge. It also pulls in `emg-memory-graph`'s
  own dependency subtree (entity resolution, trust-scoring wrapper, etc.) into
  a package that today has a much smaller, ontology-only dependency footprint.
- **Strategy B** has zero dependency impact — no new edges, no manifest
  changes, no drift-check changes — until the deferred stage begins.

## 5. Files Affected (Strategy A, if approved; none touched yet)

- `libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/context.py` —
  add `tenant: TenantId` field.
- `libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/graph_store.py`
  — delete (Protocol + `InMemoryGraphStore`/`InMemoryGraphTransaction`).
- `libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/validation.py`
  — rewrite idempotent-skip/conflict detection (lines ~251–265, ~338–349) and
  its `GraphStore` import.
- `libs/python/emg-knowledge-pipeline/src/emg_knowledge_pipeline/pipeline.py` —
  rewrite `ingest()`/`supersede_entity()`/`supersede_relationship()` against
  `transaction()`/`read()`/`stage()` instead of `begin()`/`add_entity()`/
  `commit()`.
  `pyproject.toml` — add `emg-platform-core` dependency.
- `tools/ci` dependency manifest data (wherever `check_dependency_manifest.py`
  sources its expected-edges list) — add the new edge.
- All existing `emg-knowledge-pipeline` tests that construct an
  `IngestionContext` or a fake `GraphStore` (test doubles throughout
  `libs/python/emg-knowledge-pipeline/tests/`) — updated for the new field
  and new store shape.
- A new architecture-fitness test (e.g.
  `test_only_one_graphstore_protocol_exists`), following the existing
  `test_dependency_boundary.py`/`test_no_scripting_capability.py` pattern, to
  prevent the duplicate Protocol from silently reappearing.

## 6. Risks

- **Silent semantic narrowing.** The single largest risk: if the idempotency
  rewrite (§3.A.3) is done casually, "idempotent re-ingestion" quietly starts
  accepting content that today would be flagged `GRAPH_ENTITY_CONFLICT` /
  `CODE_ONTOLOGY_NONCONFORMANT` (Entity fields the new comparison can no
  longer see: `owner`, `lifecycle_status`, `version`, `effective_to`,
  `supersedes`/`superseded_by`, domain attributes). This must be an explicit,
  documented, reviewed contract change, not an implementation detail.
- **Test-double churn.** Every existing `emg-knowledge-pipeline` test using
  the current in-memory store/`IngestionContext` shape needs updating; a
  partial rewrite risks leaving passing-but-meaningless tests behind.
  Requirement: full test-behavior review, not just "make it compile."
- **Dependency-footprint growth.** Pulling `emg-platform-core`/`emg-memory-graph`
  into `emg-knowledge-pipeline` changes what "install just the ingestion
  pipeline" means; worth confirming no circular-dependency risk given
  `emg-memory-graph` itself may (or may not) depend back on ontology types
  the pipeline also uses — needs a dependency-drift check run before merge,
  not just an assumption.
- **Deferral risk (Strategy B).** Leaving two `GraphStore` Protocols in the
  repository for longer is itself a standing architecture-fitness violation
  (exactly what ADR-027 §4 flagged) and needs a tracked-debt marker (the
  xfail/skip fitness test in §3.B.3) so it isn't forgotten.

## 7. Recommended Stage 0.1 Implementation Strategy

Recommendation: **Strategy B** — defer the actual store-unification code
change to its own reviewed follow-on stage, and close Stage 0 now on the two
items that were both fully specified by ADR-027 and are now implemented and
green (role catalog, idempotency migration).

Rationale: Stage 0 was defined as the mandatory-before-any-mutation-code
prerequisite; nothing in Stage 0/1/2 of ADR-027's migration plan actually
*requires* `emg-knowledge-pipeline`'s ingestion path to already be unified —
Stage 0.1's purpose was to prevent new mutation-API code from being written
against the wrong (duplicate) Protocol, and no new mutation-API code has been
or will be written in this session. Deferring the pipeline rewrite costs
nothing toward that goal, while attempting it now — under a "no application
commands, no feature work beyond Stage 0" constraint — risks exactly the
silent-semantic-narrowing outcome flagged in §6 if the idempotency-contract
question in §3.A.3 is not first resolved as its own reviewed decision.

If Strategy A is preferred instead, it should proceed as its own scoped
follow-up with the idempotency-semantics change in §3.A.3 written up and
approved *before* any code in `emg-knowledge-pipeline` is touched — the same
review discipline already applied to ADR-027 itself.

**Stage 0 status: role catalog and idempotency migration complete and
validated; GraphStore unification held pending a decision between the two
strategies above. Stage 1 will not begin regardless of which strategy is
chosen, per standing instruction.**
