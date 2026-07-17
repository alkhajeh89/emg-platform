# Sprint 9 Design — Core Ontology (FEAT-05-1)

Reference: Engineering Backlog v1.0 §3 (FEAT-05-1 — "Ontology Implementation:
Core + domain entity/relationship types"), §5 US-05, §6 row 7, §9 (8 story
points); Master Plan §17 (dependency order), Technology Choice #4 (Neo4j
Enterprise), §18 (Lab Prototype — ontology, not ingestion); Architecture
Baseline (Module 7 = sole system of record for organizational memory;
storage-technology independence via the Semantic Layer). ADR-016 (ownership).

## Scope

Sprint 9 implements **FEAT-05-1 only**, the first EPIC-05 (Knowledge Graph,
Module 7) feature, delivered **library-first** as `libs/python/emg-ontology` —
exactly the contract-first pattern of Modules 5–6 (`emg-policy-engine`,
`emg-audit-client`/`emg-audit-pipeline`).

In scope:
- The governed ontology model: abstract `Entity`, the `Actor`/`Artifact`/`Event`
  archetypes, and a `Relationship` model, all carrying a governance envelope
  (classification, trust score, provenance reference, owner, lifecycle, version,
  effective dating) **by construction**.
- The **Organizational** and **Risk & Safety** domains (US-05, Module 7 §4).
- Minimal Module-6 **reference** entities for linkage.
- A governed **relationship catalog** (8 types).
- A pure, storage-independent **conformance validator** with typed errors.
- A deterministic, pinned-version **ontology descriptor** with a golden test.
- The **graph-mutation audit contract** (definition only).

Explicitly **out** of scope (deferred): **FEAT-05-2** (Knowledge Ingestion
Pipeline — the physical **Neo4j binding**, live write path, and audit emission),
**FEAT-05-3** (Trust Scoring), **FEAT-05-4** (Semantic Layer — storage-
independent query/traversal), **FEAT-05-5** (Lifecycle management). Also out of
scope: any live service or HTTP surface, authentication, health/readiness,
persistence, traversal/query, embeddings/search/AI, UI, new roles, new ADRs,
and policy-engine / clearance enforcement. `services/knowledge-graph` remains
scaffolded. No Module 6 record or hash is modified.

## Pre-step: governance corrections (done first)

Before any FEAT-05-1 code, the five governance docs were corrected to reflect
reality after the Sprint 8 merge: Sprint 8 **merged** (PR #8, `79eaae6`),
**EPIC-04 complete**, current branch `feature/sprint-9-core-ontology`, Sprint 9
in progress, Module 7 in progress through FEAT-05-1
(`ARCHITECTURE_STATUS.md`, `EMG_PRODUCT_VISION.md`, `README.md`, `CHANGELOG.md`,
`SPRINT-8-STATUS.md`). Frozen `docs/architecture/*` were not touched.

## Approach

### Representation (approved decision)

The **code models are authoritative** — frozen Pydantic models. The
machine-readable **descriptor is generated from them** (`descriptor.py`), not
hand-authored. No RDF / OWL / SHACL / new graph framework, and no YAML as the
authoritative ontology definition. `ontology_schema_version` is pinned
(`identifiers.py`), and a **golden descriptor compatibility test**
(`test_descriptor_golden.py`) pins the SHA-256 of the canonical descriptor JSON
as a merge-blocking gate.

### Envelope (by construction)

`core.Entity` requires `entity_id`, `entity_type`, `classification`
(reused `emg_common_types.Classification`), `trust_score` (a required *field*,
bounded 0.0–1.0 — no scoring engine, that is FEAT-05-3), `provenance_reference`
(a `core.ProvenanceReference` **pointing into Module 6** — never a copy of audit
content), `owner`, `lifecycle_status`, `version`, `effective_from`, and optional
`effective_to`/`supersedes`/`superseded_by`/`correlation_id`. Models are frozen
and `extra="forbid"`, so missing-envelope and mass-assigned writes fail at
construction. Concrete domain entities pin `entity_type` to a `Literal`, so the
type tag cannot be forged.

### Domains and relationships

Organizational: Organization, BusinessUnit, Person, Role, System, Project,
Process. Risk & Safety: Risk, Control, Policy, Regulation, Incident, Evidence.
Module-6 references: AuditEventRef, ProvenanceRecordRef, CustodyRecordRef.
Relationship catalog (`relationships.py`): HOLDS, OWNED_BY, MITIGATED_BY,
GOVERNS, REQUIRES, DERIVED_FROM, REFERENCES, IMPACTS — each a `RelationshipRule`
with source/target `entity_type` sets, cardinality, mutability, direction, and a
self-loop flag. `IMPACTS` is scoped to Risk & Safety sources (Incident/Risk)
toward Organizational targets so no Decision Intelligence (EPIC-08) semantics
leak in; Decision/DecisionOption/DecisionRationale/Approval are **not** modeled
this sprint.

### Conformance (US-05 "rejects a non-conforming write")

`conformance.py` is a **pure, storage-independent** validator returning a typed
`ConformanceReport(ok, errors: tuple[ConformanceError, ...])`. It accepts a
model *or* a raw dict (the shape a future write would carry) and rejects:
unknown entity/relationship type, missing classification/trust_score/provenance,
out-of-range trust score, invalid lifecycle, invalid effective dates,
mass-assignment (extra fields), invalid source/target types, cardinality
violations, an edge classification below either endpoint (dominance), dangling
endpoints, and prohibited self-loops. Context a pure function cannot know
(endpoint classifications, known-id universe, sibling edges for cardinality) is
passed in by the caller, keeping it storage-independent.

### Versioning

`ontology_schema_version` (pinned), per-entity and per-relationship `version`,
`supersedes`/`superseded_by`, effective dating, and **immutable historical
versions** (frozen models, no delete path, no silent mutation). Full lifecycle
*management* is FEAT-05-5 (deferred).

### Audit and provenance contract (definition only)

`audit.py` defines the graph-mutation actions the future write path will emit
into Module 6 — `entity.created`, `entity.superseded`, `relationship.created`,
`relationship.superseded` — the `knowledge-graph` audit module tag, and a
metadata helper carrying identifiers/types only (never entity content).
**Nothing is emitted** in Sprint 9 (no write service). Correlation ids and
provenance references are represented on the models. Live delivery and any
"fail-closed on degraded audit" decision are FEAT-05-2.

## Graph technology (approved)

**Neo4j Enterprise remains the approved future store** (Master Plan Technology
Choice #4; already provisioned in `docker-compose` but unused). Sprint 9 does
**not** bind it — no Cypher, no driver, no constraints/indexes/migrations, no
seed data, no repositories. Binding is FEAT-05-2 (ingestion) / FEAT-05-4
(semantic layer). Deferring the binding is a sequencing decision within Module
7's frozen scope, not an architecture change.

## Authorization

Reuse only. **No new role, no PEP integration, no clearance enforcement, no
UI.** Sprint 9 provides classification *tagging by construction* only. This
neither adds nor weakens any existing control (there is no live surface).

## New ADR?

**No.** Neo4j is already chosen; storage-independence is already a Baseline
principle; the ontology is governed by the frozen Module 7 spec; classification/
identifiers reuse existing primitives. No architectural contradiction is proven.
Library-first / defer-binding is sequencing, consistent with prior sprints.

## Testing

See `testing-strategy.md` (Sprint 9 section): envelope-by-construction, trust
range, classification/provenance requirements, domain entities valid/invalid,
relationship catalog + endpoint compatibility, classification dominance,
cardinality, dangling endpoints, self-loops, lifecycle states, effective dates,
supersession + immutable history, mass-assignment rejection, deterministic +
golden descriptor, import/version, plus the Module 6 golden-hash regression and
the full Sprint 1–8 suites unchanged.
