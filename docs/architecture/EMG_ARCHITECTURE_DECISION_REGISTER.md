# EMG Architecture Decision Register — Open Items

**Status:** Living register — tracks unresolved architecture decisions
**Date opened:** 2026-07-25
**Purpose:** These items are identified gaps or ambiguities discovered during
`IMPLEMENTATION_GAP_ANALYSIS.md` and the Phase 3 documentation pass. They are
tracked here explicitly rather than resolved silently. An item only leaves
this register when it is marked **Accepted** with a named decider and a
dated decision — never by a later document simply assuming an answer.

This register follows the same convention already established by
`docs/architecture/backend/BACKEND_DECISION_REGISTER.md` and
`docs/security/SECURITY_DECISION_REGISTER.md`: a decision recorded here does
not constitute approved architecture unless explicitly marked Accepted.

---

## Open Architecture Decisions

| ID | Decision Area | Status | Owner | Evidence | Blocking Questions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| D-A-001 | Module Numbering Governance | **Open** | TBD | `IMPLEMENTATION_GAP_ANALYSIS.md` §6 (Gap 4a), §7 (Gap 4) | Which numbering scheme is canonical? |
| D-A-002 | Entity Resolution Ownership | **Open** | TBD | `IMPLEMENTATION_GAP_ANALYSIS.md` §2 (Gap 1) | Standalone service, part of `emg-memory-graph`, or shared library? |

### D-A-001 — Module Numbering Governance

**Current conflicting schemes:**

1. `ARCHITECTURE_STATUS.md` — Module 1–10 (Repository Structure through
   Decision Intelligence), with EPIC-01…EPIC-13 and Sprint 1–14 tracking.
2. Phase 0/1/2 roadmap structure (`docs/phases/phase-0`, `phase-1`,
   `phase-2`; current branch `phase2/sprint5-outbox-event-persistence`) —
   covers the `emg-platform-core`/`emg-persistence` foundation independent
   of any single Module 1–10 entry.
3. Reference architecture — `docs/architecture/reference/api/EMG-Enterprise-API-Architecture.md`
   and the v2.0 Enterprise Intelligence Platform document tag API groups
   `M01`–`Mxx` (observed: M02, M04, M05, M06, M09, M10, M12, M13, M16, M17,
   M18), which does not map 1:1 to scheme 1 (e.g., scheme 3's M18 = Audit
   APIs, while scheme 1's Module 6 = Audit).

**Required future decision:** create a single canonical numbering model, or
an explicit, published mapping table between all three, so that a reference
to "Module 6," "M06," and "Phase 2" cannot be mistaken for describing the
same or different things without checking source.

**Status of dependent work:** `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md`
§0 provides a working, non-authoritative reconciliation table so that
document could be written without waiting on this decision — that
reconciliation is scoped to Phase 3 only and does not substitute for a
platform-wide canonical decision.

**No implementation is blocked by this item** — it is a documentation-
governance risk, not a code dependency.

### D-A-002 — Entity Resolution Ownership

**Current state:** `libs/python/emg-entity-resolution` is a scaffolded
package with a 0-byte `pyproject.toml` and zero lines of source
(`IMPLEMENTATION_GAP_ANALYSIS.md` §2, Gap 1). `emg-memory-graph` already
contains its own, separately-built "Entity Resolution Engine
(deterministic)" as part of its existing, completed scope.

**Questions to resolve:**

- Is entity resolution meant to be a **standalone service**, independent of
  any single library?
- Is it meant to be **part of `emg-memory-graph`** — i.e., is
  `emg-entity-resolution` an abandoned or premature scaffold that should be
  removed once `emg-memory-graph`'s resolver is confirmed as the single
  implementation?
- Should it become a **shared library** that `emg-memory-graph`'s resolver
  is later extracted into, so that other future consumers (e.g., connector-
  sourced cross-system entity matching, as `emg-connectors` integrations
  mature) can use the same resolution logic without depending on the whole
  of `emg-memory-graph`?

**Binding constraint on future work:** no implementation may depend on
`emg-entity-resolution` until this ownership question is explicitly
approved. This applies to `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md`'s
Recommended Implementation Sequence (§10, step 6) and any future Knowledge
Graph Expansion (§8) or Knowledge Ingestion (ADR-020) work that might
otherwise be tempted to reference the empty package.

---

## Observations

Observations are short, evidence-based findings that do not require a
binary accept/reject decision the way the Open Architecture Decisions above
do. They record what was found and a recommendation, and are closed when the
recommendation is actioned (or explicitly declined) — not left open-ended
like D-A-001/D-A-002.

| ID | Title | Recommendation | Evidence |
| :--- | :--- | :--- | :--- |
| OBS-A-001 | Platform Core Dependency Direction Review | Accept current direction; fix a stale citation; track one adjacent finding as a future task | See below |

### OBS-A-001 — Platform Core Dependency Direction Review

**Trigger:** flagged in `IMPLEMENTATION_GAP_ANALYSIS.md` §4 (T-A-001 work) as
"reads architecturally backwards" — that characterization was made from
`pyproject.toml` alone, without reading the actual source. This observation
corrects and supersedes that earlier, under-evidenced flag.

**1. Current dependency direction (verified from source, not just
`pyproject.toml`):**

`emg-platform-core` → `emg-memory-graph`, one-directional, confirmed by:

- `emg_platform_core/ports/graph_store.py:25` — `from emg_memory_graph import
  MemoryGraph`. The `GraphStore`/`GraphTransaction` `Protocol`s are typed
  directly in terms of `MemoryGraph`: `read() -> MemoryGraph`,
  `write(..., graph: MemoryGraph, ...)`, `stage(graph: MemoryGraph)`.
- `emg_platform_core/adapters/in_memory.py:28` — `from emg_memory_graph import
  EMPTY_GRAPH, MemoryGraph`, used as the concrete in-memory representation
  backing `InMemoryGraphStore`.
- Confirmed **not circular**: `emg-memory-graph`'s own source has zero
  references to `emg_platform_core`.

**2. Whether this violates the intended layering model: No.**

`EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9 ("Domain Model") explicitly names
the Memory Graph as *"the core"* bounded context (§10, item 3: "Memory Graph
— nodes, edges, evidence, temporal, versioning, lineage (**the core**)"),
and §11 ("Service Boundaries") states the "one writer per store" rule that
`ports/graph_store.py`'s own docstring cites verbatim. A storage port
(`GraphStore`) being expressed in terms of the domain aggregate it persists
(`MemoryGraph`) is the standard Repository-pattern shape in DDD/hexagonal
architecture — it is not a "core has zero dependencies" violation, because
the Freeze does not define `emg-platform-core` as a dependency-free package;
it defines it as the **storage-independence seam**, which by construction
must speak the domain's snapshot type. The earlier "reads backwards"
characterization was a naming-expectation mismatch (the word "core"/
"foundation" suggesting zero dependencies), not an actual Freeze violation.

**Citation discrepancy found (minor, documentation-only):**
`ports/graph_store.py`'s docstring and `emg-platform-core`'s `pyproject.toml`
description both cite "Freeze §32," but `EMG_PRODUCT_ARCHITECTURE_FREEZE.md`
has only 26 numbered sections plus a "Freeze Control" section — §32 does not
exist in the current document. §9 and §11 (also cited) do exist and do
substantively support the design, as shown above. This stale citation should
be corrected to reference an existing section (or removed) — a one-line
documentation fix, not an architecture question.

**3. Possible remediation options (for the citation issue and the
naming-expectation tension; not for a real defect, since none was found):**

- **Option A — Accept as-is, fix the citation (recommended).** Correct the
  dangling "§32" reference in `ports/graph_store.py` and `pyproject.toml` to
  cite §9/§11 only (both of which are already accurate). No structural
  change. Lowest risk, matches frozen architecture as written.
- **Option B — Clarify `emg-platform-core`'s package description** to state
  explicitly that it is "a storage-independence seam built on the
  `emg-memory-graph` domain snapshot type," not a zero-dependency foundation,
  preventing future readers from making the same under-evidenced "backwards"
  assumption this observation had to correct. Low risk, documentation-only.
- **Option C — Split `emg-platform-core` into a dependency-free ports-only
  package plus a separate in-memory-adapter package.** Would restore the
  conventional "core has no outward dependencies" shape, but is a real
  package split affecting every current and future consumer (`emg-persistence`,
  and anything Phase 3 builds against `GraphStore`) for a problem that is
  presently a naming concern, not a functional one. Not recommended unless a
  concrete future need for a dependency-free port package emerges.

**4. Risk level: Low**, for the platform-core/memory-graph direction itself
— deliberate, non-circular, frozen-architecture-aligned.

**Adjacent finding (Medium risk, separate from the question asked, tracked
here only as a future candidate — not actioned):** `emg-persistence` directly
imports `emg_memory_graph` in two files
(`emg_persistence/store.py:12`, `emg_persistence/neo4j/projection.py:19`) but
does **not** declare `emg-memory-graph` in its own `pyproject.toml`
dependencies (only `emg-platform-core` and `emg-errors`). This currently
works only because `emg-platform-core` transitively pulls in
`emg-memory-graph` — if that transitive relationship ever changed,
`emg-persistence` would break at import time despite its own declared
dependencies appearing satisfied. Neither `check_dependency_manifest.py` nor
`check_dependency_drift.py` catches this class of issue today (they compare
a package's own declared deps against the manifest; they do not verify a
package's source imports against its own `pyproject.toml`). This is noted as
a candidate for a future tracked task (a new "implicit dependency" check),
not decided or actioned in this pass.

**5. Should this become an ADR or remain an implementation task?**
**Remains an implementation/documentation task — no ADR needed.** The
dependency direction is already authoritatively grounded in
`EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9/§11 (frozen); nothing here
introduces a new architectural decision requiring board-level review. The
only concrete action is Option A (fix the stale §32 citation), which is a
small documentation correction, not an ADR-worthy decision. The adjacent
`emg-persistence` finding, if pursued, would also be an implementation task
(add the missing declared dependency, and optionally extend the drift
checker), not an ADR.

**Status:** Recorded, not yet actioned. No code was modified to produce this
observation.

---

## Tracked Tasks (Phase 3)

| ID | Task | Status | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| T-A-001 | Extend dependency manifest coverage to all EMG Python components | **Done (2026-07-25)** | See below |

### T-A-001 — Extend dependency manifest coverage to all EMG Python components

**Original state:** `docker/dependencies.yaml` declared 5 of 25 total
components (18 libraries + 7 services) — `identity`, `audit`, `persistence`,
`memory-graph`, `entity-resolution`
(`IMPLEMENTATION_GAP_ANALYSIS.md` §4, Gap 2; `docs/devops/DEPENDENCY_GOVERNANCE.md`
Constraints).

**Acceptance criteria (status):**

- ✅ Every `libs/python/*` package is represented in
  `docker/dependencies.yaml` — all 18 libraries now have an entry, each
  populated from its own `pyproject.toml`'s actual declared `emg-*`
  dependencies.
- 🟡 Every service's Dockerfile dependencies are validated by
  `tools/ci/check_dependency_manifest.py` against its manifest entry — true
  for the two services that have a Dockerfile (`identity`, `audit`); the
  other five services (`authz`, `knowledge-graph`, `retrieval`,
  `ai-orchestration`, `decision-intelligence`) remain scaffolded with no
  Dockerfile, so there is nothing yet for this criterion to check for them.
  This criterion will re-apply automatically as each is implemented.
- ✅ CI (`.github/workflows/ci.yml`, `dependency-validation` job) fails the
  build on dependency drift for every represented component — verified: both
  `check_dependency_manifest.py` and `check_dependency_drift.py` now run
  against all 20 declared entries (2 services + 18 libraries) and pass
  cleanly.

**Also fixed as part of this task:** `check_dependency_manifest.py` was
hardened with the same missing-`services`-key guard
`check_dependency_drift.py` already had (raised a raw `KeyError` otherwise).

**Anomaly discovered, not resolved:** `emg-platform-core`'s `pyproject.toml`
declares `emg-memory-graph` as a dependency, which reads architecturally
backwards for a foundation package. Recorded in
`IMPLEMENTATION_GAP_ANALYSIS.md` §4 as a flagged observation, not decided
here — it did not block completing this task since the manifest reflects
declared reality rather than an idealized dependency direction.

**Sequencing:** this was implementation-sequence step 1
(`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §10) — complete before any new
Phase 3 service is scaffolded, so drift detection covers new work from day
one.

---

## Approved Implementation Sequence (Reference)

For traceability, the sequence approved alongside this register (no code
changes made in this documentation pass):

1. Extend dependency manifest coverage (T-A-001, above).
2. Add `LanguageCode`/`Locale` to `emg-common-types`.
3. Build `services/knowledge-graph`.
4. Build Enterprise API Gateway.
5. Build AI Orchestration service (`services/ai-orchestration`).
6. Build Administration service (`services/administration`, to be
   scaffolded).
7. Resolve entity-resolution ownership (D-A-002, above) before any
   integration depends on it.

This sequence is recorded here as the currently-approved plan; it is
detailed in full in `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §10.
