# Changelog

All notable changes to the EMG™ Core Platform monorepo are documented here,
generated from Conventional Commits (`CONTRIBUTING.md`).

## [Unreleased]

### Sprint 12 — EPIC-05 Knowledge Graph — Semantic Layer (FEAT-05-4) — in progress

- **New `libs/python/emg-semantic-layer`** (Module 7, EPIC-05, FEAT-05-4) — a
  **storage-independent, deterministic** Semantic Layer, delivered
  **library-first**. It **defines semantics only and executes nothing**: no
  persistence, no database driver, no networking, **no Neo4j**, no retrieval, no
  embeddings, no AI, no LLM integration, no REST API, and no UI.
  - **Graph value objects** (`graph.py`): `SemanticNode`, `SemanticRelationship`,
    `SemanticGraph` — immutable, storage-independent projections with pure lookup
    helpers (`node`, `relationships_of`, `neighbors`); node/relationship types are
    plain labels and properties are plain scalars (no ontology dependency).
  - **Closed enums** (`enums.py`): `TraversalDirection`, `FilterOperator`,
    `BooleanOperator`, `SortDirection` — a fixed operator vocabulary, never a
    caller string, callable, or expression (no injection surface).
  - **Filtering** (`filters.py`): `FilterCondition` (a leaf predicate) combined by
    a bounded, recursive `SemanticFilter`; pure data, nesting depth bounded by
    `MAX_FILTER_DEPTH`.
  - **Query model** (`query.py`): `NodeSelector` (entity lookup), `TraversalStep`
    / `SemanticTraversal` (bounded relationship traversal), `SemanticProjection`,
    `SortKey` / `SemanticOrdering`, `Pagination`, and the composed `SemanticQuery`
    — all frozen and self-validating; traversal depth ≤ `MAX_TRAVERSAL_DEPTH` and
    page size within `[MIN_PAGE_LIMIT, MAX_PAGE_LIMIT]` by construction.
  - **Planner** (`planner.py`): `plan(query)` compiles a query into an immutable,
    deterministic `SemanticPlan` (canonical order
    `SELECT → TRAVERSE → FILTER → ORDER → PAGINATE → PROJECT`) — the execution
    *semantics*, without executing. Raises `SemanticQueryError` on a semantic
    violation.
  - **Result model** (`result.py`): `SemanticResult` + `PageInfo` — the immutable
    output shape a conforming executor returns.
  - **Extension point** (`execution.py`): the `SemanticQueryExecutor` protocol —
    the **only** integration seam; a future storage binding (e.g. a Neo4j adapter)
    implements it. This library implements nothing and connects to nothing. It is
    a distinct **read-query** seam, complementary to FEAT-05-2's append-only
    `GraphStore` **persistence** contract (a future adapter may implement both).
  - **Deep immutability** (Sprint 12 review fix): `SemanticNode` /
    `SemanticRelationship` `properties` is stored as a read-only mapping over a
    private copy, so it cannot be mutated indirectly nor aliased to a caller's
    dict.
  - **Full size bounds** (review fix): centrally-defined caps for page offset
    (`MAX_PAGE_OFFSET`), selector ids (`MAX_SELECTOR_IDS`), filter width
    (`MAX_FILTER_CONDITIONS`, `MAX_FILTER_GROUPS`), projection fields
    (`MAX_PROJECTION_FIELDS`), and ordering keys (`MAX_ORDERING_KEYS`), in addition
    to the existing depth/limit/fan-out caps.
  - **Identifier/label validation** (review fix): a reusable `ensure_safe_label`
    (exported) rejects empty/whitespace-only strings and any NUL, ASCII control,
    CR/LF, or Unicode bidi override/control character across all ids, type names,
    relationship-type names, filter/projection/ordering fields, and property keys;
    legitimate Unicode is preserved.
  - **Planner** framed as a deterministic **canonical step-order** plan (review
    fix): `PlanStep.detail` is human-readable text, not an executable form.
  - **Tests**: 126 tests — the original 68 plus 58 adversarial tests (nested-
    property mutation and input-dict aliasing, offset/collection bounds at and
    above the limit, control/NUL/CR-LF/bidi identifier rejection, extreme integers,
    filter nesting/width limits, deterministic/repeated planning, the documented
    result-forgery trust boundary, and executor-protocol misuse).
  - **Dependencies**: `emg-common-types`, `emg-errors`, `pydantic` only — **not**
    `emg-ontology`, `emg-knowledge-pipeline`, or `emg-trust-scoring` (clean
    dependency direction; integration only via the extension point).
  - Quality gates: `ruff` clean, `black` clean, `mypy --strict` clean, full
    regression green. Not wired into any service; `services/knowledge-graph`
    remains scaffolded.

### Sprint 11 — EPIC-05 Knowledge Graph — Knowledge Validation & Trust Scoring (FEAT-05-3) — complete (merged — PR #12, `d27ab59`)

- **New `libs/python/emg-trust-scoring`** (Module 7, EPIC-05, FEAT-05-3) — a
  **deterministic, storage-independent** trust-scoring + advanced-validation
  ("quality gates") engine, delivered **library-first**. It has no persistence,
  no service, no Neo4j, no Semantic Layer, and no retrieval/search/embeddings/
  AI/UI.
  - **Trust factors** (`factors.py`): the eight scoring dimensions — source
    confidence, provenance quality, evidence completeness, validation status,
    ownership confidence, temporal freshness, relationship consistency, and
    ingestion quality.
  - **Signals** (`signals.py`): `TrustSignals` — a frozen, bounded model of the
    **observable inputs** the engine scores from. It has **no trust field**, so
    a caller can supply signals but never a trust value (trust cannot be
    spoofed).
  - **Scoring policy** (`policy.py`): `ScoringPolicy` — per-factor weights (sum
    ≈ 1), a temporal-decay half-life, an acceptance threshold, and a pinned
    `policy_version`; `DEFAULT_POLICY`. Frozen/immutable.
  - **Scoring engine** (`engine.py`): pure, deterministic per-factor
    computations and a weighted composite, clamped to `[0, 1]` and rounded to a
    fixed precision for reproducibility. No wall-clock, no randomness (temporal
    freshness uses an explicit `as_of`).
  - **Result + explanation** (`result.py`): `TrustScoreResult` — a frozen
    composite score with a per-factor **breakdown** (raw sub-score, weight,
    weighted contribution), the policy version, an acceptance verdict against the
    threshold, and a human-readable explanation. Immutable and reproducible.
  - **Advanced validation** (`validation.py`): typed `QualityCheck` /
    `QualityGateReport` for evidence completeness, provenance integrity,
    ownership consistency, identifier consistency, ontology consistency,
    relationship consistency, duplicate-confidence, temporal validation, and
    lifecycle validation.
  - **Combined evaluation** (`evaluate.py`): `evaluate(...)` returns a frozen
    `TrustEvaluation` (quality-gate report + trust score) computed from one set
    of signals.
- **Security posture:** trust is **computed from signals, never a caller-chosen
  value**; the engine is pure and deterministic (identical signals + policy ⇒
  identical, byte-reproducible output — pinned by a golden test); results are
  immutable (frozen); ratios/penalties are clamped so a single manipulated
  signal cannot dominate the composite.
- Scope note: Sprint 11 implements **FEAT-05-3 only**. **FEAT-05-4 (Semantic
  Layer + Neo4j adapter) and FEAT-05-5 (Knowledge Lifecycle & Versioning) are
  deferred.** The engine is **not** wired into the ingestion pipeline this sprint
  (that would change merged FEAT-05-2 behaviour; it is a follow-up for the future
  live ingestion service). `services/knowledge-graph` remains scaffolded. **No
  Neo4j, no new database, no Modules 8–10 work, no new role, no new ADR.** No
  Module 6 record or hash is modified.
- New docs: `docs/engineering/sprint-11-design.md`,
  `libs/python/emg-trust-scoring/README.md`; Sprint 11 sections added to
  `docs/engineering/testing-strategy.md` and
  `docs/engineering/security-limitations.md`.

### Sprint 10 — EPIC-05 Knowledge Graph — Knowledge Ingestion Pipeline (FEAT-05-2) — complete (merged, PR #10, `bf8d460`)

- **New `libs/python/emg-knowledge-pipeline`** (Module 7, EPIC-05, FEAT-05-2) —
  the **storage-independent Knowledge Ingestion Pipeline** that converts
  validated ontology models into persistent graph operations, delivered
  **library-first** on top of `emg-ontology` (models + conformance) and
  `emg-audit-client` (Module-6 audit contract). No retrieval, search,
  embeddings, AI, UI, or Neo4j binding this sprint.
  - **Ingestion request models** (`requests.py`): `EntityIngestionRequest`,
    `RelationshipIngestionRequest`, `IngestionBatch` — frozen, `extra="forbid"`
    (mass-assignment rejected), length-bounded free-text, and **no
    server-assigned fields** (a producer cannot supply `entity_id`, `owner`,
    `provenance_reference`, or `trust_score`).
  - **Ingestion context** (`context.py`): the server-side authority —
    authenticated `source_principal`, `source_type` (system/document/api/ai/
    human), correlation id, ingest time, owner, and the interim trust policy.
  - **Deterministic idempotency** (`idempotency.py`): entity/relationship ids
    derived from `(source_principal, source_type, type, natural_key)` /
    `(source_principal, relationship_type, from_id, to_id)`, so re-ingesting the
    same payload never creates duplicates.
  - **Resolvers** (`resolver.py`): entity resolution by natural key, relationship
    endpoint resolution, and duplicate detection.
  - **Ingestion validator** (`validation.py`): bounds payload/field sizes, runs
    ontology conformance, and checks entity uniqueness, relationship validity,
    identifier validity, provenance/classification/trust/ownership/effective
    dates, duplicate entities/relationships, and **cyclic dependency** (for
    acyclic relationship types). **No persistence occurs before validation
    succeeds.**
  - **Graph store + transaction abstraction** (`graph_store.py`): a
    storage-independent `GraphStore` Protocol and a `GraphTransaction`
    (begin/commit/rollback) with an append-only **`InMemoryGraphStore`** (no
    update/delete path). A failed persistence rolls back — **no partial graph,
    no partial relationships**. A `GraphStore` Protocol lets a Neo4j adapter be
    added later (FEAT-05-4) without coupling business logic.
  - **Pipeline orchestrator** (`pipeline.py`) + **result model** (`result.py`) +
    **typed ingestion errors** (`errors.py`): validate → order → persist in one
    transaction → emit audit → return a typed `IngestionResult` (created /
    idempotent-skipped ids, emitted audit-event refs, correlation id).
  - **Module-6 audit integration** (`audit.py`): each graph mutation emits a
    `SubmittedAuditEvent` (via the `emg-audit-client` `AuditSink`) with action
    `entity.created` / `relationship.created` / `entity.superseded` /
    `relationship.superseded`, module `knowledge-graph`. The entity's
    `provenance_reference` **points to that audit event** (single system of
    record — no audit content copied); correlation ids are preserved end to end.
  - **Security posture:** `owner`, `provenance_reference`, and `trust_score` are
    **server-assigned** from the ingestion context — caller-supplied values are
    structurally impossible (not fields on the request models). Free-text is
    length-bounded and batch size is capped to prevent oversized-payload DoS.
- Review-fix round (independent Sprint 10 review — APPROVE WITH MINOR FIXES):
  the ingestion validator's `DERIVED_FROM` cycle detector was **rewritten from
  recursive to iterative** (explicit-stack DFS) so a valid in-limit batch (a
  chain deeper than Python's recursion limit but within
  `MAX_BATCH_RELATIONSHIPS`) can no longer raise an uncaught `RecursionError`;
  semantics and the typed `CODE_CYCLIC_DEPENDENCY` rejection are unchanged, and
  `MAX_BATCH_RELATIONSHIPS` was not reduced. Adversarial regression tests were
  added (deep-chain no-recursion, duplicate relationship in batch,
  same-id/different-content conflict, concurrent different-content). The review's
  C2 finding (pre-commit created/skipped reporting + deduplicated double audit
  emission) is **documented as deferred hardening**, not fixed (the graph is
  always correct and audit ids are deterministic/Module-6-deduped).
- Scope note: Sprint 10 implements **FEAT-05-2 only**. **FEAT-05-3 (Validation &
  Trust Scoring), FEAT-05-4 (Semantic Layer + Neo4j adapter), and FEAT-05-5
  (Knowledge Lifecycle & Versioning) are deferred.** `services/knowledge-graph`
  remains scaffolded. **No Neo4j binding, no new database, no Modules 8–10 work,
  no new role, no new ADR.** No Module 6 record or hash is modified.
- New docs: `docs/engineering/sprint-10-design.md`,
  `libs/python/emg-knowledge-pipeline/README.md`; Sprint 10 sections added to
  `docs/engineering/testing-strategy.md` and
  `docs/engineering/security-limitations.md`.

### Sprint 9 — EPIC-05 Knowledge Graph — Core Ontology (FEAT-05-1) — complete (merged, PR #9, `2fcbaa9`)

- **New `libs/python/emg-ontology`** (Module 7, EPIC-05, FEAT-05-1) — the
  governed **Core Ontology** as a **library-first** model + conformance layer,
  the same contract-first pattern as `emg-policy-engine` and `emg-audit-client`.
  No persistence, no live service, no Neo4j binding this sprint (those are
  FEAT-05-2 / FEAT-05-4).
  - **Core archetypes**: an abstract `Entity` and the `Actor`, `Artifact`,
    `Event` archetypes, plus a governed `Relationship` model. Every concrete
    entity requires, by construction, an `entity_id`, `entity_type`,
    `classification` (reused `emg_common_types.Classification`), `trust_score`,
    `provenance_reference` (a *reference* into Module 6, never a copy), `owner`,
    `lifecycle_status`, `version`, and effective dating.
  - **Organizational domain**: Organization, BusinessUnit, Person, Role, System,
    Project, Process. **Risk & Safety domain**: Risk, Control, Policy,
    Regulation, Incident, Evidence. Minimal Module-6 **reference** types
    (AuditEvent / ProvenanceRecord / CustodyRecord) for linkage only — no audit
    content copied.
  - **Governed relationship catalog**: HOLDS, OWNED_BY, MITIGATED_BY, GOVERNS,
    REQUIRES, DERIVED_FROM, REFERENCES, IMPACTS — each with source/target types,
    direction, cardinality, classification, provenance, effective dating,
    version, and mutability/supersession semantics. No traversal or query
    execution.
  - **Conformance validator** (`conformance.py`) — pure, storage-independent,
    returning typed machine-readable errors; rejects unknown entity/relationship
    types, missing classification/trust_score/provenance, out-of-range trust
    score, invalid lifecycle state, invalid source/target types, cardinality
    violations, an edge classification below either endpoint, dangling
    endpoints, prohibited self-loops, invalid effective dates, and mass-assigned
    extra fields.
  - **Versioning**: a pinned `ontology_schema_version`, per-entity and
    per-relationship `version`, supersession references, effective dating, and
    immutable historical versions (no delete path, no silent mutation). Full
    lifecycle-state management is FEAT-05-5 (deferred).
  - **Deterministic ontology descriptor** generated from the code models
    (the models are authoritative — no RDF/OWL/SHACL/YAML authority), guarded by
    a **golden descriptor compatibility test**.
  - **Audit contract** (definition only): the future graph-mutation event names
    (`entity.created`, `entity.superseded`, `relationship.created`,
    `relationship.superseded`) and correlation/provenance representation are
    defined in the models; live audit delivery is deferred to the FEAT-05-2
    write service (Sprint 9 has no write path).
- Scope note: Sprint 9 implements **FEAT-05-1 only**. **FEAT-05-2 (Knowledge
  Ingestion Pipeline), FEAT-05-3 (Validation & Trust Scoring), FEAT-05-4
  (Semantic Layer), and FEAT-05-5 (Knowledge Lifecycle & Versioning) are
  deferred.** `services/knowledge-graph` remains scaffolded. No Neo4j binding,
  no Modules 8–10 work, **no new role, no new ADR**, and no policy-engine /
  classification-clearance enforcement (Sprint 9 provides classification
  *tagging by construction* only). No Module 6 record or hash is modified.
- New docs: `docs/engineering/sprint-9-design.md`, `libs/python/emg-ontology/README.md`;
  Sprint 9 sections added to `docs/engineering/testing-strategy.md` and
  `docs/engineering/security-limitations.md`.

### Sprint 8 — EPIC-04 Audit Query & Reporting Interface (FEAT-04-4) — complete (merged, PR #8, `79eaae6`)

- `libs/python/emg-audit-client` (0.3.0): **richer, backward-compatible query
  models (FEAT-04-4)** — `AuditQuery` gains optional `module`, `action`,
  `outcome`, `source_system`, `classification`, `has_provenance` filters and an
  opaque `cursor`; `CustodyQuery` gains `classification` and `cursor`. Every new
  field defaults to `None`, so the Sprint 6/7 query surface is unchanged.
- `libs/python/emg-audit-pipeline` (0.3.0): **stable keyset (cursor)
  pagination** (`pagination.py`: `encode_cursor` / `decode_cursor`, a versioned
  opaque token over the server-assigned `sequence_number` / `chain_sequence`) —
  deterministic ordering, no duplicates, no skipped records; a malformed cursor
  is rejected (`CURSOR_INVALID`), never silently ignored. Both audit and custody
  in-memory + PostgreSQL stores apply the new filters and cursor through their
  `query` paths.
- `services/audit` (0.3.0): additive reporting endpoints — `GET
  /audit/events/page` and `GET /audit/custody/events/page` (cursor-paginated),
  `GET /audit/events/export` and `GET /audit/custody/export` (`format=json|csv`,
  no HTML/UI). The Sprint 6 `GET /audit/events` and Sprint 7 `GET
  /audit/custody/events` keep their list shape and gain the new optional
  filters. Report export walks the result set one store query per page (keyset),
  never per row (no N+1). All read endpoints remain least-privilege and
  restricted to the existing `svc-audit` role.
- `tools/seed-data/postgres/004_audit_reporting_indexes.sql` — **index-only,
  additive** composite `(filter, sequence)` indexes supporting classification-/
  source-system-/module-filtered cursor pagination and per-evidence custody
  export. It creates indexes only: no column/row is added, altered, dropped,
  rewritten, re-hashed, or deleted, so no stored `event_hash` changes and the
  golden hash-compatibility tests still pass. Idempotent SQL, no Alembic.
- Scope note: classification here is a **filter** dimension only. Clearance-based
  classification-aware read *authorization* (restricting which classifications a
  principal may see) is a deliberate follow-up requiring a human reader role and
  an authorization decision — see `docs/engineering/security-limitations.md`. No
  new role, no new ADR, no policy-engine enforcement wired into `services/audit`
  this sprint; no EPIC-05 / Module 7–10 work; backend only.
- Pre-condition fix (test-only, separate from FEAT-04-4): two stale assertions
  in `libs/python/emg-audit-client/tests/test_import.py` that were red on the
  merged mainline (`__version__` expected `0.1.0`; an `AuditEvent` built without
  the now-required `source_principal`) were corrected so the regression gate is
  actually green. No production code changed for this fix.
- **EPIC-04 exit:** with FEAT-04-4 delivered, EPIC-04 (Audit Platform) is
  functionally complete (FEAT-04-1 through FEAT-04-4), unblocking the EPIC-05
  dependency gate (Backlog §7; Master Plan §17) for a future sprint.

### Sprint 7 — EPIC-04 Audit Platform completion (FEAT-04-2, FEAT-04-3) — complete, pending merge

- `libs/python/emg-audit-client`: **Provenance Record Model (FEAT-04-2)** — a
  versioned `ProvenanceRecord` (source system, source component, originating
  actor, originating service principal, correlation id, event timestamp vs.
  ingestion timestamp, classification, transformation history, parent/source
  event references, evidence origin, collection method, schema version) added
  as an **optional** field on `AuditEvent`/`SubmittedAuditEvent`, plus a
  `schema_version` discriminator. New `CustodyEvent`/`SubmittedCustodyEvent`
  models and a `CustodyEventStore` protocol for **FEAT-04-3**.
- `libs/python/emg-audit-pipeline`: **version-aware canonical hashing** — the
  version-1 canonical payload is byte-identical to Sprint 6 (no provenance
  keys), so every existing version-1 record re-verifies to its stored hash;
  version-2 events additionally hash the provenance record. Provenance is
  validated/redacted with the same bounded-metadata / sensitive-key guards.
  **Digital Evidence Chain-of-Custody (FEAT-04-3)**: a separate append-only
  custody ledger (in-memory + PostgreSQL) with a centralized global hash chain,
  a per-evidence custody sequence, tamper/gap/invalid-schema detection that
  returns an explicit failure result (never a 500), and
  `(source_principal, custody_event_id)` idempotency with server-assigned
  `source_principal`.
- `services/audit`: additive custody endpoints (`POST /audit/custody/events`,
  `GET /audit/custody/events`, `GET /audit/custody/integrity`) — least-privilege
  and service-authenticated, restricted to the existing `svc-audit` role. The
  FEAT-04-1 ingest/query/integrity surface is unchanged.
- `tools/seed-data/postgres/002_audit_provenance.sql` (adds `schema_version` +
  nullable `provenance` columns and provenance indexes — no rewrite of existing
  rows) and `003_evidence_custody.sql` (new append-only `evidence_custody_events`
  table, `REVOKE ALL … FROM PUBLIC`, INSERT/SELECT-only application role, no
  UPDATE/DELETE/TRUNCATE path). Idempotent SQL, no Alembic (Decision B carried
  forward).
- Backward compatibility: existing Sprint 6 version-1 audit records remain
  readable and byte-for-byte verifiable; no published record is rewritten,
  re-hashed, migrated, or mutated. A **golden Sprint-6 v1 hash-compatibility
  test** is added as a merge-blocking gate.
- Scope note: Sprint 7 is an approved **controlled split** — it implements
  **FEAT-04-2 and FEAT-04-3 only**. **FEAT-04-4 (Audit Query & Reporting
  Interface) is explicitly deferred** to the immediate next sprint, which must
  deliver it before EPIC-05 / Module 7 begins. **EPIC-04 remains incomplete
  until FEAT-04-4 is delivered.** Engineering sequencing only — no Architecture
  Baseline change, no Module 6 redesign, no new ADR, no new role.
- Security review: a final security-focused review of Sprint 7 concluded
  **APPROVE**, with no blocking or high-risk findings. Per the Definition of
  Done, this audit/provenance change still requires formal organizational
  Security Reviewer sign-off prior to merge; no such external sign-off is
  claimed here.
- Technical debt (carried forward, unchanged this sprint): the duplicated
  service-token validator (`services/audit` vs. `services/identity`) and
  PostgreSQL connection pooling / async-safe DB access remain documented
  production-hardening items in `docs/engineering/security-limitations.md`;
  neither `emg-service-auth` nor connection pooling was introduced in Sprint 7
  (no proven Sprint-7 defect required it).

### Sprint 6 — EPIC-04 Audit Platform (FEAT-04-1) — complete (merged, PR #6, `1fe6bc7`)

- New `libs/python/emg-audit-client`: the audit event contract — `AuditEvent`
  model, `AuditSink` and `AuditEventStore` protocols, `AuditQuery`, and
  outcome types. Reuses `emg_common_types.Classification` / `CorrelationId`;
  no new cross-cutting primitives.
- New `libs/python/emg-audit-pipeline`: the audit pipeline core — canonical
  event hashing, a **centralized** hash chain and sequence assignment (chains
  are constructed by the audit store, never by individual producer services),
  `InMemoryAuditEventStore` (tests) and a PostgreSQL-backed append-only store,
  integrity verification (out-of-band mutation detection), event-id
  idempotency, and metadata/secret-key validation.
- `services/audit` **activated** as a minimal live service (Module 6) over the
  shared libraries: authenticated ingestion, minimal US-04 query (by actor,
  time range, correlation id), integrity verification, and health/readiness
  reporting that surfaces audit degradation. It owns the single append-only
  store; it is a thin deployment shell over the libraries.
- `tools/seed-data/postgres/`: idempotent initialization SQL creating the
  append-only `audit_events` table and an application role granted INSERT and
  SELECT only (no application UPDATE/DELETE path). Schema-migration tooling
  (e.g. Alembic) is documented as a later production-hardening item.
- `services/identity`: migrated from `StructuredLogAuditSink` to a
  Protocol-preserving `PipelineAuditSink`. The existing `AuditEventSink`
  Protocol and every `record_*` call site are unchanged. The new sink forwards
  each event to the audit service and, on transient failure, spools durably
  with bounded exponential backoff and an explicit dead-letter state; it
  continues emitting ADR-015 structured telemetry throughout and never
  silently claims an event was recorded. Existing login/authentication
  endpoints do not fail solely because the audit service is temporarily
  unavailable (Sprint 6 compatibility posture; see
  `docs/engineering/security-limitations.md`).
- Compatibility: `StructuredLogAuditSink` is retained as the degraded-mode
  fallback limb and test double.
- Scope note: Sprint 6 implements **FEAT-04-1 only**. FEAT-04-2 (Provenance
  Record Model), FEAT-04-3 (Digital Evidence Chain-of-Custody), and FEAT-04-4
  (full Audit Query & Reporting Interface) are shifted to later Audit sprints —
  an engineering-sequencing decision that alters no Backlog feature-to-epic
  assignment and requires no new ADR. Sprint 6 implements only the minimal
  query capability US-04 explicitly requires.
- Security review: a final security-focused review of Sprint 6 concluded
  **APPROVE WITH MINOR FIXES**; every required minor fix (advisory-lock
  concurrency serialization, per-principal idempotency, durable-spool
  fsync + truthful failure reporting, defensive integrity verification,
  route-level query validation, and SQL-role hardening) was resolved. Two
  items were recorded as documented technical debt rather than fixed in
  Sprint 6 (duplicated service-token validator; Postgres connection pooling /
  async-safe DB access) — see `docs/engineering/security-limitations.md` and
  `SPRINT-6-STATUS.md` §4b for the full findings-and-dispositions table. Per
  the Definition of Done, this audit/provenance change still requires formal
  organizational Security Reviewer sign-off prior to merge.
- New docs: `docs/engineering/sprint-6-design.md`; Sprint 6 sections added to
  `docs/engineering/security-limitations.md` and
  `docs/engineering/testing-strategy.md`.

### Sprint 5 — EPIC-03 Authorization Completion (FEAT-03-3, FEAT-03-4) — complete

- `libs/python/emg-policy-engine`: **RBAC Baseline Roles (FEAT-03-3)** — a
  governed, versioned role catalog (`roles.py`: `RoleDefinition`,
  `RoleCategory`, `ROLE_CATALOG`) enumerating the eight roles already proven
  to exist in the repository and the Keycloak realm seed (`platform-user`,
  `investigator`, `decision-maker`, `knowledge-steward`; `service-account`,
  `svc-identity`, `svc-authorization`, `svc-audit`). This is a role
  *vocabulary* consumed by the ABAC engine's `required_roles` conditions —
  **not** a second authorization or enforcement mechanism, no permission
  matrix, no role hierarchy/inheritance, no new roles invented.
- `libs/python/emg-policy-engine`: `validate_policy_config` gains an
  additive, **advisory** check — any `PolicyRule.required_roles` value not
  present in `ROLE_CATALOG` is reported as a validation problem (never a hard
  load failure; a malformed file remains the only hard error).
- `libs/python/emg-policy-engine`: **Authorization Testing Harness
  (FEAT-03-4)** — a small reusable toolkit (`testing.py`:
  `AuthorizationScenario`, `assert_scenario`, `run_scenarios`) for
  declarative positive/negative authorization testing, with no pytest
  runtime dependency and no YAML DSL.
- `services/identity`: `tests/test_authz_scenarios.py` — real adoption of
  the harness against the existing `policy.example.yaml`, proving the harness
  works outside its own unit tests.
- `tools/seed-data/keycloak/emg-realm.json`: role `description` fields only
  updated to point at the new catalog — no role name, id, or grant changed.
- Scope note: the Backlog's Sprint 5 row (§6) also lists FEAT-04-1 (Audit
  Event Pipeline); it has been **rescheduled to the next Audit implementation
  sprint**. Engineering-sequencing decision only — no Architecture Baseline
  change, no Module 6 redesign, no new ADR. FEAT-04-1 is **not** implemented
  in Sprint 5.
- New docs: `docs/engineering/sprint-5-design.md`; Sprint 5 sections added to
  `libs/python/emg-policy-engine/README.md`, `services/identity/README.md`,
  `docs/engineering/security-limitations.md`, and
  `docs/engineering/testing-strategy.md`.

### Sprint 4 — EPIC-03 Authorization Platform (FEAT-03-1, FEAT-03-2)

- `libs/python/emg-auth-client` (0.2.0): the Policy Enforcement Point
  contract — `Decision`, `AuthorizationRequest`, `PolicyEnforcementPoint`
  (a `typing.Protocol`), and `ServicePrincipalLike` (a structural Protocol
  matching `services/identity`'s `ServicePrincipal` field-for-field, so a
  shared library can type "either identity kind" without importing from a
  service).
- New package `libs/python/emg-policy-engine` (0.1.0): `PolicyEngine` (ABAC
  evaluation — default-deny, fail-closed, deny-overrides combining),
  `PolicyConfig`/`PolicyRule` (pydantic schema, no configurable "default
  effect"), `load_policy_config`/`default_policy_config`/`validate_policy_config`
  (same safe-default-on-missing-file, hard-error-on-malformed-file pattern
  as Sprint 3's `federation.py`), and `LocalPolicyEnforcementPoint`.
- `services/identity` (0.4.0): reference integration only — `GET
  /authz/check` (always HTTP 200, `Decision` in the body; introspection,
  not enforcement), `policy_enforcement_point_dependency` (loads
  `config/policy.example.yaml`), `get_current_identity` (accepts either a
  human `Principal` or a machine `ServicePrincipal`, used only by this new
  endpoint), and `AuditEventSink.record_authorization_decision` (both allow
  and deny decisions are logged — US-03). No existing Sprint 2/3 route,
  dependency, or behavior changed.
- `services/identity/config/policy.example.yaml`: illustrative local-dev
  ABAC rules exercising an allow rule, a deny rule that overrides it for a
  specific role (deny-overrides), and a service-scope-based allow rule.
- Explicitly not implemented this sprint (approved scope boundary):
  FEAT-03-3 (RBAC Baseline Roles), FEAT-03-4 (Authorization Testing Harness),
  and any live, network-reachable `services/authz` HTTP service —
  `services/authz` remains scaffolded.
- Governance file corrections (`CLAUDE_WORKFLOW.md`, `ARCHITECTURE_STATUS.md`,
  `EMG_PRODUCT_VISION.md`): converted from RTF-content-in-a-`.md`-file to
  genuine plain UTF-8 Markdown, and `ARCHITECTURE_STATUS.md`/
  `EMG_PRODUCT_VISION.md` corrected to match the actual repository state
  (architecture-approved vs. engineering-complete status per module, only
  ADR-014–017 present, roadmap deferring to the Engineering Backlog instead
  of restating it).
- New docs: `docs/engineering/sprint-4-design.md`; extended
  `docs/engineering/security-limitations.md` with Sprint 4 controls and
  limitations.
- New tests: `libs/python/emg-auth-client/tests/test_import.py` extended
  for the new PEP types; `libs/python/emg-policy-engine/tests/test_import.py`,
  `test_engine.py` (9 cases covering the full ABAC combining/condition
  semantics), `test_loader.py`; `services/identity/tests/test_authz_router.py`
  (HTTP-level, loads the real `policy.example.yaml`, covers both identity
  kinds, deny-overrides, default-deny, and audit logging).

### Sprint 3 — EPIC-02 Identity (FEAT-02-3, FEAT-02-4)

- `services/identity`: OAuth 2.0 Client Credentials (M2M) authentication —
  `KeycloakClient.client_credentials_token()` for outbound service calls,
  `ServiceTokenValidator` for inbound validation (RS256/JWKS signature,
  issuer, audience, expiry, registered-client, optional scope) of other
  services' tokens (FEAT-02-3).
- `services/identity`: representative service identities registered for the
  Identity, Authorization, and Audit services (`service_registry.py`,
  `tools/seed-data/keycloak/emg-realm.json`) — registration only, no
  downstream service business logic implemented.
- `services/identity`: structural separation between human sessions and
  service identities — `ServicePrincipal` is a distinct type from
  `Principal`; service tokens (RS256/JWKS) and human session tokens (HS256)
  are cryptographically unrelated trust paths, so one cannot be presented
  where the other is required.
- `services/identity`: identity federation readiness (`federation.py`) — a
  provider-agnostic configuration schema and validator for LDAP/Active
  Directory/external OIDC/SAML readiness, claim and group-to-role mapping
  projection, and air-gapped-safe defaults. No external directory is
  connected (FEAT-02-4).
- New endpoints: `GET /auth/service-session` (service-token "whoami"),
  `GET /federation/providers` (redacted listing), `GET /federation/health`
  (configuration validation status).
- `services/identity`: rate-limiting readiness for `/auth/login`
  (`rate_limit.py`, `InMemoryRateLimiter`) and a secret-redaction utility
  (`redact.py`) applied to the `/federation/providers` response.
- `tools/seed-data/keycloak/emg-realm.json`: three new service-account-only
  confidential clients, their least-privilege realm roles, and a client
  scope adding the `emg-internal-services` audience to service-account
  tokens.
- New docs: `docs/engineering/service-identity-registration.md`,
  `docs/engineering/federation-readiness.md`,
  `docs/engineering/security-limitations.md`.
- New tests: `test_service_token_validator.py`,
  `test_separation_human_vs_service.py`, `test_federation.py`,
  `test_redaction.py`, `test_rate_limit.py`, `test_service_auth_router.py`,
  `test_federation_router.py`, plus Client Credentials coverage added to
  `test_keycloak_client.py` and a login-rate-limit 429 test added to
  `test_auth_router.py`. `test_integration_live_keycloak.py` is an
  opt-in, skipped-by-default suite documenting the live-Keycloak procedure.
- **Fix (test flakiness, `services/identity/tests/test_session.py`):**
  `test_verify_rejects_tampered_signature` corrupted only the final
  base64url character of a JWT signature, which carries "don't-care"
  padding bits and roughly 1-in-4 decodes to identical bytes — an existing
  Sprint 2 test with a latent ~25% flake rate, discovered while extending
  the tampering test pattern for Sprint 3's `ServiceTokenValidator`. Fixed
  to corrupt a middle character instead (deterministic). See
  `SPRINT-3-STATUS.md`.

### Sprint 2 — EPIC-02 Identity (FEAT-02-1, FEAT-02-2)

- `services/identity`: Keycloak-backed authentication (Direct Access Grants)
  against the local-dev realm seeded in
  `tools/seed-data/keycloak/emg-realm.json` (FEAT-02-1).
- `services/identity`: EMG-minted session issuance, refresh (with rotation),
  and expiry, independent of Keycloak's own token lifetimes; session claims
  carry `roles`/`attributes` matching `emg_auth_client.Principal` for
  Module 5's future PEP (FEAT-02-2).
- `SessionAuthClient`: concrete `emg_auth_client.AuthClient` implementation
  (Sprint 1 shipped the Protocol only).
- Interim authentication-event logging (`StructuredLogAuditSink`) standing
  in for the audit pipeline until FEAT-04-1 (Sprint 5-6).
- Wired `identity` into `docker-compose.yml` and a per-service CI workflow
  (`.github/workflows/service-identity.yml`) using the Sprint 1 reusable
  pipeline template.
- **Fix (libs/python/emg-telemetry):** `get_logger()`'s `extra=` handling
  crashed with `KeyError: Attempt to overwrite 'module' in LogRecord`
  whenever a caller passed the ADR-015 schema field `module` — a reserved
  `logging.LogRecord` attribute name. Discovered while wiring Sprint 2's
  audit logging (US-02's "failed authentication is logged" acceptance
  criterion depends on this). Fixed by namespacing the internal attribute
  names; the public `extra=` schema (`actor`, `module`, `action`, `outcome`)
  is unchanged. See `SPRINT-2-STATUS.md` for details.

### Sprint 1 — EPIC-01 Foundation (FEAT-01-1 through FEAT-01-4)

- Repository bootstrap: monorepo structure, branch protection, CODEOWNERS
  derived from ADR-016 (FEAT-01-1).
- Shared libraries scaffolding: common types, error handling, telemetry
  client, auth client interfaces, API client conventions (FEAT-01-2).
- Local development environment: containerized orchestration, seed data
  fixture scaffolding (FEAT-01-3).
- CI pipeline skeleton: staged pipeline template all services inherit
  (FEAT-01-4).
