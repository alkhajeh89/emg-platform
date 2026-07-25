# EMG Implementation Gap Analysis

**Status:** Evidence-based snapshot
**Date:** 2026-07-25
**Scope:** `libs/python/`, `services/`, `docs/`, `docker/`, `tools/`
**Method:** Every claim below is grounded in a direct repository read (file
counts, line counts, `git log`, manifest parsing) performed on this date, not
carried forward from prior status documents. Where this analysis disagrees
with an existing document, that document is named explicitly rather than
silently corrected.

---

## 1. Purpose

Before adding Phase 3 architecture and new ADRs, this document establishes
what is actually built, what is actually missing, and where existing
documentation disagrees with the repository. It is the required input for
`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` and ADR-019/020/021 — those
documents build on this one rather than re-deriving it.

---

## 2. Shared Libraries (`libs/python/`) — Engineering Status

| Package | Files | LOC (src) | Tests | Status |
| --- | --- | --- | --- | --- |
| `emg-common-types` | 3 | 55 | 1 | Complete — minimal by design (cross-cutting value types only) |
| `emg-errors` | 3 | 86 | 1 | Complete — minimal by design |
| `emg-telemetry` | 3 | 149 | 1 | Complete — observability foundation |
| `emg-auth-client` | 6 | 223 | 1 | Complete |
| `emg-api-contracts` | 3 | 84 | 1 | Complete — minimal by design |
| `emg-audit-client` | 6 | 633 | 1 | Complete |
| `emg-audit-pipeline` | 8 | 1,713 | 11 | Complete (Module 6 / EPIC-04) |
| `emg-policy-engine` | 7 | 573 | 6 | Complete |
| `emg-ontology` | 11 | 1,232 | 7 | Complete (Module 7, FEAT-05-1) |
| `emg-knowledge-pipeline` | 11 | 1,407 | 7 | Complete (Module 7, FEAT-05-2) |
| `emg-trust-scoring` | 9 | 801 | 5 | Complete (Module 7, FEAT-05-3) |
| `emg-semantic-layer` | 11 | 1,030 | 8 | Complete (Module 7, FEAT-05-4) |
| `emg-knowledge-lifecycle` | 14 | 1,125 | 9 | Complete (Module 7, FEAT-05-5) |
| `emg-connectors` | 21 | 2,157 | 11 | Complete (EPIC-13, additive) |
| `emg-memory-graph` | 20 | 2,713 | 19 | Complete |
| `emg-platform-core` | 11 | 535 | 6 | Complete (Phase 1) |
| `emg-persistence` | 35 | 2,958 | 23 | Complete through outbox/projection (Phase 2) |
| `emg-entity-resolution` | 1 | **0** | 0 | **Stub only** — see Gap 1 |

All packages except `emg-entity-resolution` are editable-installed and
importable. Total: 17 populated libraries, 1 empty stub.

### Gap 1 — `emg-entity-resolution` is an empty stub with an unclear relationship to existing entity-resolution logic

`libs/python/emg-entity-resolution/src/` contains a single file and zero
lines of code; `pyproject.toml` is 0 bytes (no declared dependencies, no
package metadata). Meanwhile, `emg-memory-graph` already implements an
"Entity Resolution Engine (deterministic)" internally as part of its own
scope. This raises an open architectural question that predates this
analysis and is not answered anywhere in the repository: is
`emg-entity-resolution` meant to (a) be deleted as an abandoned scaffold, (b)
become a standalone package that `emg-memory-graph`'s resolver is later
extracted into, or (c) serve an entity-resolution use case distinct from
`emg-memory-graph`'s (e.g., cross-source enterprise entity matching, as
`emg-connectors` integrations mature)? This must be resolved with an explicit
decision before any further work references `emg-entity-resolution` — it is
flagged here rather than resolved, since resolving it is a product/ontology
decision, not an inference this analysis can safely make.

---

## 3. Services (`services/`) — Engineering Status

| Service | LOC (src) | Status | Governing module |
| --- | --- | --- | --- |
| `identity` | 2,332 | **Live** — Docker image builds and runs, `/healthz` returns 200 | Module 4 |
| `audit` | 1,205 | **Live** — Docker image builds and runs, `/healthz` returns 200 | Module 6 |
| `authz` | 0 | Scaffolded (`service.yaml` present, `src/`/`tests/` are `.gitkeep`-only) | Module 5 |
| `knowledge-graph` | 0 | Scaffolded | Module 7 |
| `retrieval` | 0 | Scaffolded | Module 8 |
| `ai-orchestration` | 0 | Scaffolded | Module 9 |
| `decision-intelligence` | 0 | Scaffolded | Module 10 |

The five scaffolded services all carry a properly filled `service.yaml`
(`owner`, `steward`, `module`, `status: scaffolded`) per ADR-016 — this is
correctly governed placeholder state, not an oversight. `tools/scripts/new-service.sh`
generates this exact shape and its own generated README explicitly instructs:
*"Do not introduce business logic here until the owning Epic/Feature's sprint
begins."* This is a deliberate gate, not a gap — it is listed here as
**status**, not as something to silently fix.

This does mean, however, that every "Enterprise Platform Layer" requested for
Phase 3 (AI Orchestration, Knowledge Ingestion service surface, Enterprise
API Gateway, Administration Portal) currently has **zero running code**. The
corresponding libraries backing several of these layers (`emg-ontology`,
`emg-knowledge-pipeline`, `emg-trust-scoring`, `emg-semantic-layer`,
`emg-knowledge-lifecycle`) already exist and are tested; what is missing is
the service shell that exposes them and binds them to Neo4j/PostgreSQL,
consistent with the library-first pattern already used for Modules 4–7.

---

## 4. Dependency Manifest Coverage — Architectural Gap (RESOLVED 2026-07-25)

**Update:** this gap is resolved. At the time this analysis was first written,
`docker/dependencies.yaml` declared 5 entries (`identity`, `audit`,
`persistence`, `memory-graph`, `entity-resolution`), leaving **15** of the 18
`libs/python/` packages uncovered (the original text below undercounted this
as 13 — corrected here for the record):

```
api-contracts, audit-client, audit-pipeline, auth-client, common-types,
connectors, errors, knowledge-lifecycle, knowledge-pipeline, ontology,
platform-core, policy-engine, semantic-layer, telemetry, trust-scoring
```

T-A-001 (`EMG_ARCHITECTURE_DECISION_REGISTER.md`) has been completed: all 15
libraries were added to `docker/dependencies.yaml`, each populated from its
own `pyproject.toml`'s actual declared `emg-*` dependencies (verified via
`tomllib`, not guessed). `docker/dependencies.yaml` now declares 20 entries
(2 services + 18 libraries — every `libs/python/*` package); both
`check_dependency_manifest.py` and `check_dependency_drift.py` pass cleanly
against all 20. T-A-001's acceptance criteria are met except "every service
Dockerfile dependencies are validated," which only applies to `identity` and
`audit` today since the other five services have no Dockerfile yet
(unimplemented, per §3) — there is nothing for that criterion to check until
those services exist.

**Anomaly noted, then reviewed:** `emg-platform-core`'s `pyproject.toml`
declares `emg-memory-graph` as a dependency. This was initially flagged here
as reading "architecturally backwards," based on `pyproject.toml` alone. A
follow-up architecture review — `EMG_ARCHITECTURE_DECISION_REGISTER.md`
OBS-A-001 — read the actual source and the Freeze document and found this
characterization was premature: the dependency is deliberate, non-circular,
and explicitly grounded in `EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9/§11
(`MemoryGraph` is the frozen domain core; a storage port being typed in
terms of the domain aggregate it persists is standard hexagonal/DDD shape,
not a violation). See OBS-A-001 for the full analysis, a minor stale-citation
fix it recommends, and one adjacent finding (an undeclared transitive
`emg-persistence` → `emg-memory-graph` import) it surfaced but did not
action. The manifest entry for `platform-core` reflects what `pyproject.toml`
actually declares, which OBS-A-001 confirms is correct as-is.

### Gap 2 — Dependency drift detection covers roughly 20% of the monorepo (RESOLVED)

`check_dependency_manifest.py` and `check_dependency_drift.py` (hardened
earlier this session — see `docs/devops/DEPENDENCY_GOVERNANCE.md`) are
correct and passing, and now validate all 20 declared components rather than
5. This is no longer a live gap; see the Update above.

---

## 5. Documentation — Two Distinct Tiers

Measuring average lines-per-document by top-level `docs/` directory exposes a
clear split:

| Directory | Files | Avg lines/doc | Character |
| --- | --- | --- | --- |
| `architecture` | 26 | 261 | Substantive — ADRs, baseline, backlog, master plan |
| `sprints` | 18 | 287 | Substantive — proposals, reviews, status |
| `phases` | 7 | 262 | Substantive — Phase 0/1/2 plans and architecture |
| `product` | 2 | 255 | Substantive — vision, architecture freeze |
| `ai-context` | 3 | 334 | Substantive |
| `frontend` | 120 | 52 | **Templated** — most files are 8–40 lines |
| `security` | 12 | 29 | **Templated** — most files are 8–38 lines |
| `infrastructure` | 25 | 17 | **Templated** |
| `enterprise-design` | 4 | 17 | **Templated** |
| `backend` | 22 | 38 | **Templated** |
| `devops` | 13 | 40 | Mixed — most templated, `DEPENDENCY_GOVERNANCE.md` (172 lines) is substantive |

### Gap 3 — A large fraction of `docs/` is placeholder scaffolding, not reviewed architecture

`docs/frontend/design/FRONTEND_I18N.md` (previously reviewed this session) is
representative of the `frontend`, `security`, `infrastructure`, and
`enterprise-design` trees: fixed-template sections (Purpose / Scope /
Responsibilities / Dependencies / etc.) with one-line, generic content and no
concrete technical decisions (no library named, no data shape, no enforcement
mechanism). This is not a defect to "fix" wholesale — most of these documents
correspond to services or UI layers that have not been built yet — but it
means these documents **cannot be treated as authoritative** the way
`docs/architecture/*` and `docs/phases/*` can. Any future work citing a
`docs/frontend/*`, `docs/security/*`, or `docs/infrastructure/*` document as a
binding constraint should verify its actual content first rather than assume
depth matching its title.

---

## 6. A Third, More Extensive Reference-Architecture Corpus Also Exists

Before writing anything for Phase 3, a search of `docs/architecture/reference/`
surfaced a large, pre-existing body of architecture material that Gap 4 (as
originally scoped) did not account for:

- `docs/architecture/reference/api/EMG-Enterprise-API-Architecture.md` — 638
  lines, styled "Official API Contract · Version 1.0," covering API Gateway
  Design (§16), Administration APIs (§31), Audit APIs (§38 governance, §32
  privileged Audit APIs), Search/Graph/Decision/Knowledge/Risk/Investigation
  APIs, and full REST/GraphQL/event/error/pagination standards.
- `docs/architecture/reference/enterprise/EMG-v2-Enterprise-Intelligence-Platform-Architecture.md`
  — 938 lines, two parts: Part I (Ch. 1–26, "v1 foundation, carried forward")
  and Part II (Ch. 27–44, "v2.0 expansion" — Enterprise Organizational Brain,
  Decision Intelligence Engine, AI Agent Ecosystem, Enterprise Knowledge
  Fabric, Enterprise Command Center, etc.). Its own header states **Status:
  Draft for Architecture-Board / Defense / Procurement Review — no code
  until sign-off**, i.e. this is not yet an accepted document the way
  ADR-014…018 are.
- `docs/architecture/reference/system/EMG-System-Architecture-Design-SAD.md`
  — a "Master Engineering Blueprint," which states it "derives from
  Enterprise Architecture v2.0 (**approved**)" — in apparent tension with
  the v2.0 document's own "Draft ... no code until sign-off" status line.
  This inconsistency is noted, not resolved, here.
- `docs/architecture/reference/data/EMG-Enterprise-Data-Architecture.md` and
  `docs/architecture/reference/ux/EMG-Enterprise-UX-Architecture-Design-System.md`
  round out the corpus.

### Gap 4a — A third module-numbering scheme, inconsistent with the other two

The API Architecture reference doc tags each API group with an `(M##)`
module identifier — e.g. Search APIs **(M17)**, Graph APIs **(M04)**,
Decision APIs **(M05)**, Administration APIs **(M12)**, Audit APIs **(M18)**.
This does not match `ARCHITECTURE_STATUS.md`'s Module 1–10 scheme (where
Audit is **Module 6** and Search is **Module 8**), nor the Phase 0/1/2 scheme
used on the current branch. Three numbering vocabularies now coexist across
the repository's architecture documentation. This is flagged as a
**documentation-governance risk**, not resolved in this pass — reconciling
which numbering is authoritative is a decision for whoever owns
`ARCHITECTURE_STATUS.md` and the reference corpus, not an inference this
analysis will make unilaterally.

### Note — the reference corpus already explicitly deferred localization

The UX reference document lists "full localization/RTL" under **"Deferred
(post-prototype)"** (§ Prototype scope) and mentions RTL only as a one-line
design principle elsewhere ("language/RTL support is built in
(localization-ready)"). ADR-018 (2026-07-24) supersedes that deferral: it
makes bilingual/RTL support a **mandatory, foundation-level invariant**
rather than a post-prototype nice-to-have. This is exactly the kind of
"decision not yet fixed in the reference corpus" the SAD document itself says
should be raised as an ADR ("Where a team needs a decision not fixed here, it
is raised as an ADR (App. B), not resolved locally") — which is precisely
what ADR-018 already did, and what ADR-019/020/021 (this pass) do for AI
Orchestration, Knowledge Ingestion, and Enterprise API Strategy specifically
with respect to bilingual alignment.

### Consequence for Phase 3 documentation

Given this corpus already contains detailed, section-numbered treatment of
API Gateway design, Administration APIs, AI/Decision/Knowledge APIs, and an
Enterprise Intelligence Platform reference model,
`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` (this pass) is written as an
**alignment and binding layer** on top of this existing material — citing the
governing reference section for each of the eight requested layers rather
than re-deciding API standards, gateway behavior, or platform capability
scope from scratch. Its net-new content is: (a) explicit reconciliation
pointers between the three numbering schemes where they overlap, (b) the
ADR-018 bilingual-alignment requirement per layer (genuinely absent from the
existing corpus, per the note above), and (c) grounding against the actual
current repository state established in Sections 2–3 of this analysis
(which libraries exist, which services are still zero-LOC scaffolds).

---

## 7. `ARCHITECTURE_STATUS.md` Is Stale Relative to the Current Branch

`docs/architecture/ARCHITECTURE_STATUS.md` states `Current Branch:
feature/sprint-14-universal-connector-framework` and documents Sprints 1–14
under an EPIC/FEAT numbering scheme (EPIC-01…EPIC-13, Modules 1–10). It makes
**no mention** of `emg-platform-core`, `emg-persistence`, the `GraphStore`/
`RevisionRepository`/Outbox/projection work, or the Phase 0/1/2 numbering
scheme used on the actual current branch,
`phase2/sprint5-outbox-event-persistence`.

### Gap 4 — Two parallel tracking schemes exist and are not reconciled

The repository has, in effect, two roadmap/status vocabularies in active use:

1. **Module/EPIC/FEAT/Sprint 1–14** (`ARCHITECTURE_STATUS.md`,
   `EMG_Engineering_Backlog_v1.0.md`, `EMG_Engineering_Master_Plan.md`) —
   covers Modules 1–10 (Identity through Decision Intelligence) and treats
   persistence as part of Module 7's future Neo4j binding.
2. **Phase 0/1/2, Sprint 1–5** (`docs/phases/phase-0`, `phase-1`, `phase-2`,
   this session's work) — covers the `emg-platform-core` / `emg-persistence`
   build-out (GraphStore, migrations, revisions, outbox) as a cross-cutting
   foundation independent of any single Module.

These are not in conflict technically — Phase 2's persistence engine is
exactly what Module 7 (and eventually 8–10) will bind to — but
`ARCHITECTURE_STATUS.md` does not yet say so, and its "Current Branch" field
is out of date. This is flagged as a **risk**, not silently corrected here:
`ARCHITECTURE_STATUS.md` describes itself as tracking a frozen architecture
baseline, and updating it is a documentation-governance action distinct from
writing new Phase 3 architecture. This analysis adds the three new ADRs to
its ADR table only (additive, matching how ADR-018 was already listed there)
and leaves the stale Module/Sprint narrative untouched pending an explicit
decision on reconciling the two schemes.

---

## 8. `emg-common-types` Has No Language/Locale Value Type

`emg-common-types` currently defines exactly two things: `Classification`
(government-style classification labels) and `CorrelationId`. Per its own
module docstring, it is scoped to hold only "cross-cutting, storage- and
domain-agnostic value types." ADR-018 requires `source_language`,
`translations`, and `locale` concepts across the ontology, ingestion, API,
AI-response, and frontend layers — but no shared `LanguageCode`/`Locale` type
exists anywhere in the repository today for those layers to converge on.

### Gap 5 — No canonical language/locale type

Without a single shared type, each future layer (ontology, ingestion, API
contracts, AI orchestration) risks inventing its own ad hoc language
representation, which is precisely the "retrofitted" outcome ADR-018 is
meant to prevent. `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` and
ADR-019/020/021 (below) all reference a proposed `LanguageCode`/`Locale`
addition to `emg-common-types`, modeled on how `Classification` already
works. This is a **documented recommendation**, not an implementation — no
code changes are made in this pass, per the current task's explicit
architecture-only scope.

---

## 9. Docker / CI Status

- `docker/dependencies.yaml` and its two validation scripts are correct and
  passing (see Gap 2 for coverage, not correctness).
- `.github/workflows/ci.yml` runs `quality`, `typecheck`, and
  `dependency-validation` jobs; the two previously duplicated workflow files
  were removed this session (commit `f4c6aef`).
- `identity` and `audit` Dockerfiles follow one consistent, documented
  pattern (`docs/devops/DEPENDENCY_GOVERNANCE.md` §Docker Dependency Rules).
  No other service has a Dockerfile yet (none of the five scaffolded
  services do — expected, since none have implementation).

No changes were made in this section; it is confirmed clean.

---

## 10. Summary — Gaps Requiring a Decision (Not Fixed in This Pass)

| # | Gap | Blocking? | Owner decision needed | Tracked as |
| --- | --- | --- | --- | --- |
| 1 | `emg-entity-resolution` empty stub, unclear scope vs. `emg-memory-graph` | No | Product/ontology: delete, extract, or repurpose | `EMG_ARCHITECTURE_DECISION_REGISTER.md` D-A-002 (Open) |
| 2 | Manifest covered 5/25 components | **Resolved 2026-07-25** | — | `EMG_ARCHITECTURE_DECISION_REGISTER.md` T-A-001 (Done) |
| 3 | Most of `docs/frontend`, `security`, `infrastructure`, `enterprise-design` are placeholder-depth | No | None required now; treat as non-authoritative until filled | Not registered — no decision needed |
| 4 | `ARCHITECTURE_STATUS.md` stale vs. current branch; two parallel tracking schemes | No | Documentation governance: reconcile Module/EPIC scheme with Phase 0/1/2 scheme | `EMG_ARCHITECTURE_DECISION_REGISTER.md` D-A-001 (Open) |
| 4a | A third `(M##)` numbering scheme in the reference corpus conflicts with both of the above; v2.0 Enterprise Intelligence doc's "Draft" status conflicts with the SAD's claim it derives from an "approved" v2.0 | No | Documentation governance: designate one authoritative numbering scheme and resolve the draft/approved status conflict | `EMG_ARCHITECTURE_DECISION_REGISTER.md` D-A-001 (Open) |
| 5 | No shared `LanguageCode`/`Locale` type in `emg-common-types` | No (architecture-only this pass) | Confirmed direction in Phase 3 doc; implementation follow-up | Approved sequence step 2 (register, "Approved Implementation Sequence") |

None of these gaps are resolved by this document. Gaps 1, 4, and 4a are
formally tracked as open decisions, and Gap 2 as an open task, in
`EMG_ARCHITECTURE_DECISION_REGISTER.md` — this analysis identifies them; it
does not close them. None of these gaps block writing
`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` or ADR-019/020/021 — they are
referenced by those documents where relevant
(Gaps 1, 4a, and 5 in particular) rather than resolved by them.
