# Testing Strategy

Reference: Engineering Master Plan §16.

Standard pyramid: unit tests for business logic, integration tests across
service boundaries, end-to-end tests for full user-journey scenarios —
layered with each module's own testing obligations as they are implemented
(Module 7 §26, Module 8's grounding validation tests, Module 9 §17's
AI/agentic threat cases, Module 10's Decision Replay reconstruction tests).

Sprint 1 status: `libs/python/*` packages carry unit tests
(`tests/test_import.py` per package) exercising the scaffolded shared-library
surface. `/services` test directories are scaffolded (`tests/.gitkeep`) with
no test suites yet, since no service has business logic this sprint.
Performance/load testing against ADR-017's compounded-load model begins once
a full request chain exists (EPIC-07 onward).

## Authorization testing harness (Sprint 5, FEAT-03-4)

`emg_policy_engine.testing` is the platform's shared, reusable toolkit for
authorization testing: `AuthorizationScenario` (a declarative
principal/resource/action/expected-outcome expectation), `assert_scenario`
(raises `AssertionError` on mismatch), and `run_scenarios` (batch runner
returning failure messages). Any service embedding the PEP
(`emg_policy_engine`) uses this to express positive/negative authorization
cases declaratively instead of hand-writing engine or HTTP assertions. It has
no pytest runtime dependency (plain `assert` / returned strings) and no
YAML/DSL layer. Reference adoption:
`services/identity/tests/test_authz_scenarios.py`, which runs the harness
against that service's real `config/policy.example.yaml`.

## Audit pipeline testing (Sprint 6, FEAT-04-1)

Audit tests are split across the libraries and the service, and run without
Docker or a database by default:

- `libs/python/emg-audit-pipeline/tests` — unit tests for canonical hashing,
  the append-only `InMemoryAuditEventStore` (sequence/chain assignment, US-04
  queries), event-id idempotency, hash-chain tamper detection, and
  pre-persistence validation/redaction.
- `services/audit/tests` — HTTP-level tests against the live service with an
  in-memory store and an injected local RSA keypair validator: authenticated
  ingest, schema rejection (422), sensitive-metadata rejection (400),
  duplicate idempotency, correlation propagation, redaction, integrity/tamper,
  and endpoint authorization (ingest vs. `svc-audit`-only read/integrity).
- `services/identity/tests/test_audit_pipeline.py` — the `PipelineAuditSink`
  degraded-mode behavior (Decision C): successful delivery, transient failure
  → durable spool → retry → dead-letter, continued ADR-015 telemetry, the
  never-raises guarantee, and Protocol preservation vs. `StructuredLogAuditSink`.
- `libs/python/emg-audit-pipeline/tests/test_integration_live_postgres.py` —
  an **opt-in, skipped-by-default** suite (see its module docstring) that runs
  against a real Postgres from `docker-compose` to prove persistence, DB-layer
  append-only enforcement (INSERT/SELECT-only role denied UPDATE/DELETE),
  idempotency, and integrity.

## Provenance + chain-of-custody testing (Sprint 7, FEAT-04-2 + FEAT-04-3)

- `libs/python/emg-audit-pipeline/tests/test_backward_compat_hashing.py` — the
  **merge-blocking backward-compatibility gate**: the version-1 canonical
  payload is byte-for-byte identical to Sprint 6, a pinned literal golden
  version-1 hash still matches, a stored version-1 record re-verifies, and a
  mixed version-1/version-2 store verifies intact. If this fails, a change has
  silently altered the hash of already-published audit records.
- `libs/python/emg-audit-pipeline/tests/test_provenance.py` — provenance version
  stamping (server-derived), persistence, provenance tamper detection, and
  validation/redaction of oversized / secret-shaped provenance.
- `libs/python/emg-audit-pipeline/tests/test_custody_stores.py` — custody
  append-only, global + per-evidence sequencing, hash-chain links, queries,
  per-principal idempotency isolation, and the no-mutation/no-delete surface.
- `libs/python/emg-audit-pipeline/tests/test_custody_integrity.py` — custody
  mutation, deletion, non-increasing global sequence, per-evidence sequence gap,
  and schema-violating-row detection (each an explicit failure, never a raise).
- `services/audit/tests/test_provenance_api.py` — HTTP: provenance-carrying
  ingest persists a version-2 event, keeps the chain intact, and rejects
  oversized provenance (400).
- `services/audit/tests/test_custody_api.py` — HTTP: least-privilege
  (`svc-audit`-only) custody record/query/integrity, authorization negatives,
  idempotency, route-limit 422, invalid-action 422, and tamper detection.
- `libs/python/emg-audit-pipeline/tests/test_integration_live_postgres_custody.py`
  — an **opt-in, skipped-by-default** suite: custody persistence, DB-layer
  append-only enforcement, per-principal idempotency, integrity, a **25-thread
  concurrency** test (unique + contiguous global sequence, one valid chain), and
  the **FEAT-04-2 migration backward-compatibility** check (a version-1 and a
  version-2 event coexist and verify intact after `002` runs).

## Audit Query & Reporting Interface testing (Sprint 8, FEAT-04-4)

- `libs/python/emg-audit-pipeline/tests/test_pagination.py` — the cursor codec
  (`encode_cursor` / `decode_cursor` round-trip, opacity, and `CURSOR_INVALID`
  rejection of malformed / non-numeric / negative tokens), stable keyset
  pagination over the in-memory audit + custody stores (**every record exactly
  once, in order — no duplicates, no skips**, including when new rows are
  appended mid-walk), cursor+filter composition, and the new
  classification / module / action / outcome / source_system / has_provenance
  filters.
- `services/audit/tests/test_reporting_api.py` — HTTP: classification and
  richer-filter queries; `GET /audit/events/page` and
  `GET /audit/custody/events/page` cursor walks (no dupes / no skips, terminal
  cursor contract); JSON + CSV export for both surfaces (stable CSV header/
  column order, filtered export); `422` on invalid classification / export
  format, `400 CURSOR_INVALID` on a bad cursor; **least-privilege authorization**
  (the new page/export endpoints reject a non-`svc-audit` principal); backward
  compatibility (the Sprint 6 `GET /audit/events` still returns a list); and a
  **report-walk performance** test proving export issues one store query per
  page, never one per row (no N+1).
- `libs/python/emg-audit-pipeline/tests/test_integration_live_postgres_reporting.py`
  — an **opt-in, skipped-by-default** suite: filters + keyset cursor pagination
  through real SQL (deterministic, no dupes / no skips), the `004` composite
  reporting indexes exist in `pg_indexes`, and — proving `004` is index-only /
  additive — existing rows and their hashes are untouched (integrity still
  intact after `004` runs).
- The **merge-blocking golden hash gate** (`test_backward_compat_hashing.py`,
  Sprint 7) continues to run unchanged: FEAT-04-4 adds only read paths and
  index-only SQL, so every stored `event_hash` is byte-for-byte unchanged.

## Core Ontology testing (Sprint 9, FEAT-05-1)

`libs/python/emg-ontology/tests` — pure, storage-independent unit tests (no
Docker, no database, no Neo4j; the ontology is a model + conformance library):

- `test_import.py` — version, pinned `ontology_schema_version`, public-surface
  export, and the registry counts (16 entity types, 8 relationship types).
- `test_core_envelope.py` — the governance envelope **required by
  construction**: missing classification / trust_score / provenance rejected at
  construction; trust-score range (boundary + out-of-range); frozen/immutable
  entities; extra-field (mass-assignment) rejection; invalid lifecycle state;
  effective-date validation; self-supersession rejection; and
  supersession-creates-a-new-version-while-the-original-stays-immutable.
- `test_domains.py` — every Organizational and Risk & Safety entity constructs
  with the envelope and pins its `entity_type`; a forged type tag is rejected; a
  missing envelope is non-conformant; archetype assignment is correct.
- `test_relationships.py` — the catalog contains exactly the approved eight
  types, each fully specified (source/target/cardinality/mutability/direction/
  self-loop); the `Relationship` model requires the envelope and is
  frozen/extra-forbidding.
- `test_conformance.py` — the US-05 "conformance test rejects a non-conforming
  write" criterion, one required rejection category per test: unknown entity/
  relationship type, missing classification/trust_score/provenance, out-of-range
  trust score, invalid lifecycle, invalid effective dates, mass-assignment,
  invalid source/target type, self-loop, dangling endpoint, classification
  dominance (edge below an endpoint), and cardinality — plus the accept paths
  and the typed-error raising helpers.
- `test_descriptor_golden.py` — the descriptor is deterministic (byte-stable)
  and its SHA-256 is pinned as a **merge-blocking golden gate**
  (`_GOLDEN_DESCRIPTOR_HASH`), the same pattern as the Module 6 golden audit
  hash; structural assertions confirm sorted output and the required-envelope
  flags on every entity.
- `test_audit_contract.py` — the graph-mutation action names and audit-module
  tag the future FEAT-05-2 write path will honor are pinned, and the metadata
  helper is proven to carry identifiers/types only (never entity content).

The Module 6 **golden audit-hash regression** and the full Sprint 1–8 suites run
unchanged alongside these; FEAT-05-1 is a new, isolated library and touches no
Module 1–6 code, record, or hash.

## Knowledge Ingestion Pipeline testing (Sprint 10, FEAT-05-2)

`libs/python/emg-knowledge-pipeline/tests` — pure unit tests (no Docker, no
database, no Neo4j; the pipeline persists through an in-memory `GraphStore`
adapter):

- `test_ingestion.py` — successful end-to-end ingestion (validate → persist →
  emit audit), **idempotent re-ingestion** (nothing created, everything skipped,
  no new audit events), deterministic ids stable across pipelines, **server-side
  assignment** of owner/trust/provenance, provenance→audit-event linkage,
  correlation-id preservation, per-source-type trust defaults, and
  per-principal id isolation.
- `test_validation.py` — **no persistence before validation succeeds**, one
  typed problem per rejection category: unknown entity type, invalid
  relationship endpoint types, dangling endpoints, in-batch duplicates, cyclic
  `DERIVED_FROM` lineage, self-loops, invalid effective dates, unknown domain
  attributes, oversized batch, and oversized attribute values.
- `test_transactions.py` — **rollback on persistence failure leaves no partial
  graph** (and emits no audit), explicit `rollback()` and context-manager
  rollback-on-exception, and the append-only guarantee (no update/delete on the
  store or transaction).
- `test_security.py` — server-assigned fields are **not fields on the request
  models** (structural), mass-assignment via extra fields and via `attributes`
  is rejected, owner/trust/provenance are never taken from the request, and
  natural-key / attribute-count / attribute-length bounds (oversized-payload DoS
  prevention).
- `test_audit_and_supersession.py` — audit module/actor/source/outcome, metadata
  carries identifiers/types only (no entity content), provenance references the
  audit event, `build_mutation_event` supports **all four** actions
  (`entity.created` / `relationship.created` / `entity.superseded` /
  `relationship.superseded`), and the minimal supersession primitives emit the
  `*.superseded` + `*.created` pair while leaving the prior (historical) version
  immutable.
- `test_concurrency_and_batch.py` — a 16-thread concurrent identical ingestion
  collapses to a single graph (idempotent, no fork, no unhandled error), batch
  dependency ordering (entities before relationships) resolves same-batch
  endpoints, a partially-invalid batch is atomically rejected, and (Sprint 10
  review round) **concurrent different-content ingestion for the same
  deterministic id** yields exactly one persisted, uncorrupted entity with every
  losing attempt returning a typed error.
- Sprint 10 review-round adversarial tests: **deep-chain cycle detection**
  (`test_validation.py`) — a `DERIVED_FROM` chain far deeper than Python's
  recursion limit is validated without `RecursionError` both at the
  `_detect_cycle` unit level (5000 deep) and end-to-end through the pipeline
  (1100 deep, within batch limits), and the cyclic variant is still rejected
  with `CODE_CYCLIC_DEPENDENCY`; **duplicate relationship in a batch**
  (`CODE_DUPLICATE_RELATIONSHIP_IN_BATCH`); and **same-deterministic-id /
  different-content** (`test_transactions.py`) — the store rejects it with
  `GRAPH_ENTITY_CONFLICT` and the pipeline rejects it at validation, in both
  cases leaving the original record unchanged, while identical content is an
  idempotent no-op.
- `test_import.py` — version, public surface, and that `InMemoryGraphStore` /
  its transaction satisfy the `GraphStore` / `GraphTransaction` Protocols.

The **Module 6 golden audit-hash** and the **Sprint 9 golden ontology
descriptor** regressions run unchanged; FEAT-05-2 is a new isolated library that
touches no Module 1–6 code, record, or hash, and re-uses (does not modify) the
`emg-ontology` models and the `emg-audit-client` contract.

## Validation & Trust Scoring testing (Sprint 11, FEAT-05-3)

`libs/python/emg-trust-scoring/tests` — pure unit tests (no Docker, no database,
no service; the engine is deterministic and storage-independent):

- `test_engine.py` — the per-factor calculations (source confidence, provenance
  quality, evidence completeness, validation status, ownership confidence,
  relationship consistency, ingestion quality), factor clamping to `[0, 1]`, the
  weighted composite (== sum of contributions), determinism (identical repeated
  evaluations), **immutable** result and breakdown, and the **golden score
  pins** (high-trust composite `0.971667`, low-trust `0.216667` under
  `DEFAULT_POLICY`) — a merge-blocking reproducibility gate analogous to the
  Module 6 golden hash.
- `test_temporal_and_edges.py` — temporal-freshness **decay** (maximal at the
  effective date, halves after one half-life, monotonic decay, future-dated
  fully fresh), **expiry** and **retired/superseded** freshness = 0, conflicting
  evidence with no support, all-default signals still valid, malformed-signal
  rejection at construction, and the duplicate-likelihood gate.
- `test_quality_gates.py` — every typed quality gate (evidence completeness,
  provenance integrity, ownership/identifier/ontology/relationship consistency,
  duplicate confidence, temporal, lifecycle), report aggregation, error vs.
  warning severity (warnings do not fail the report), immutability, and the
  combined `evaluate(...)`.
- `test_security_and_policy.py` — **trust cannot be spoofed** (`TrustSignals`
  has no trust field and rejects extra fields), signals are immutable, a single
  **manipulated signal cannot dominate** (an inflated evidence count caps at the
  factor clamp), evaluation is **reproducible from serialized signals**, the
  policy validates/normalizes weights (missing/unknown rejected, arbitrary
  weights normalized to sum 1) and is immutable, a policy change moves the score
  deterministically, and the `signals_from_entity` ontology adapter derives
  envelope signals without using the entity's own `trust_score`.
- `test_import.py` — version, public surface, and factor/check/policy-version
  counts.

The **Module 6 golden audit-hash** and the **Sprint 9 golden ontology
descriptor** regressions run unchanged; FEAT-05-3 is a new isolated library that
touches no Module 1–6 code, record, or hash, does not modify `emg-ontology` or
`emg-knowledge-pipeline`, and is not wired into the ingestion pipeline this
sprint.

## Semantic Layer testing (Sprint 12, FEAT-05-4)

`libs/python/emg-semantic-layer/tests` — pure unit tests (no Docker, no database,
no service, no network; the layer defines semantics only and executes nothing):

- `test_graph.py` — `SemanticNode` / `SemanticRelationship` / `SemanticGraph`
  construction, defaults, scalar-only properties (nested/non-scalar rejected),
  deterministic property key sorting, **immutability**, empty-id/type rejection,
  duplicate node/relationship-id rejection, and the pure lookup helpers (`node`,
  `relationships_of`, `neighbors`) including their deterministic ordering.
- `test_filters.py` — per-operator operand validation (nullary operators reject a
  value; `IN`/`NOT_IN` require a non-empty collection; scalar operators reject a
  collection; comparison operators require a non-null operand; text operators
  require a string), condition immutability, empty-group "match all", `NOT` must
  wrap exactly one child, computed nesting `depth`, and the `MAX_FILTER_DEPTH`
  bound (exactly-at-max allowed, one deeper rejected).
- `test_query_model.py` — `NodeSelector` (by ids/type/filter; fully-unbounded and
  empty-id rejected; immutable), `SemanticTraversal` (depth = step count;
  ≥ 1 step; `MAX_TRAVERSAL_DEPTH` bound), `TraversalStep` (direction default,
  relationship-type fan-out bound, empty-type rejection), `SemanticProjection`
  (default projects-all; duplicate/empty fields rejected), `SemanticOrdering`
  (non-empty, distinct fields), `Pagination` (defaults and `[MIN, MAX]` limit +
  non-negative offset bounds), and `SemanticQuery` (default bounded page,
  immutability, traversal-depth accessor).
- `test_planner.py` — the **deterministic execution model**: minimal plan
  (`SELECT → PAGINATE`), the full **canonical order**
  (`SELECT → TRAVERSE → FILTER → ORDER → PAGINATE → PROJECT`), determinism
  (identical query ⇒ identical plan), sequential step indices, one `TRAVERSE`
  step per hop, match-all filter / project-all elided, pagination always present,
  ordering-key order preserved in detail, and plan immutability.
- `test_result.py` — `PageInfo` count bounds, `SemanticResult` page/graph
  consistency, immutability, and the `SemanticQueryExecutor` **protocol** verified
  structurally against an in-memory test double (the library ships no executor)
  and a negative `isinstance` check.
- `test_security.py` — **no arbitrary code / no injection surface** (operator must
  be a closed enum; an injection-like string value is stored as inert data and
  never interpreted; a callable property value is rejected; unknown query fields
  rejected), all query parts **frozen/immutable**, **deterministic** execution
  model, **bounded traversal depth** (at construction and a defensive
  planner-level `SemanticQueryError` for a query assembled via `model_construct`),
  the typed `SemanticQueryError` (an `emg_errors.ValidationError` subclass with a
  stable code), and unbounded-selector rejection.
- `test_import.py` — version, the eight named abstractions + extension point +
  planner + error type on the public surface, and an assertion (in a clean
  subprocess) that **no storage/network/AI module** (`neo4j`, `requests`,
  `httpx`, `sqlalchemy`, `torch`, `openai`) is imported by the layer.
- `test_adversarial.py` (Sprint 12 review fixes) — **deep immutability** (node/
  relationship `properties` reject item-assignment, key-addition, and deletion;
  a caller's input dict cannot mutate the model afterward; mutation through a
  graph-returned node fails; dump/equality preserved); **size bounds** (page
  offset, selector ids, filter conditions/groups width, projection fields, and
  ordering keys — each tested at the exact limit and one above, plus extreme
  integers and the retained zero/negative rejections); **identifier validation**
  (NUL, ASCII control, CR/LF, tab, bidi override/isolate/mark, and empty/
  whitespace-only rejected across ids, type names, relationship types/endpoints,
  filter/projection/ordering fields, and property keys; legitimate Arabic/
  accented-Latin/CJK labels preserved); **filter nesting** at and above
  `MAX_FILTER_DEPTH`; **deterministic/repeated planning**; the **result-forgery
  trust boundary** (constructable but consistency-checked); and **executor-
  protocol misuse** (missing `execute` fails the structural check).

The **Module 6 golden audit-hash** and the **Sprint 9 golden ontology
descriptor** regressions run unchanged; FEAT-05-4 is a new isolated library that
touches no Module 1–6 code, record, or hash, does not modify `emg-ontology`,
`emg-knowledge-pipeline`, or `emg-trust-scoring`, and is not wired into any
service this sprint.

## Knowledge Lifecycle & Versioning testing (Sprint 13, FEAT-05-5)

`libs/python/emg-knowledge-lifecycle/tests` — pure unit tests (no Docker, no
database, no service, no network, no scheduler; the library defines lifecycle
semantics only and executes nothing):

- `test_states.py` — the transition table pinned as a **golden set** (exact legal
  transitions), no self-transitions, `allowed_transitions` consistency, restore-
  transition detection, and the live-state set.
- `test_version.py` — `VersionIdentifier` (canonical key/sort key, version bounds,
  immutability), `VersionMetadata` (optional note, immutability), and
  `KnowledgeVersion` construction + helpers, plus rejection of self-parent,
  cross-entity parent, non-decreasing parent, and an inverted effective window.
- `test_events.py` — `LifecycleEvent` accepts only legal transitions (illegal and
  self transitions rejected), flags the restore transition, and is immutable.
- `test_chain.py` — `VersionChain` lineage helpers (`active`, `roots`, `latest`,
  `children`, `lineage`, `get`) and their determinism, plus every structural
  rejection: empty, mixed entity, duplicate identifier, orphaned parent, duplicate
  active, and cyclic input (assembled via `model_construct`, rejected when building
  a chain).
- `test_validation.py` — `LifecycleValidator.validate_chain(...)` enumerates every
  issue as a typed `ChainIssue` (duplicate-active, mixed-entity, orphan, cycle,
  cross-entity/non-decreasing parent, inverted window, empty) without raising;
  `assert_valid_chain`, `validate_transition`, `assert_transition`, and a policy
  that disables the restore transition.
- `test_retention.py` — deterministic retention windows per state, archive
  eligibility (including the `archive_after_days` delay and the not-eligible cases:
  live states, already-archived, indefinite retention), restore eligibility and
  its window, determinism (identical `as_of` ⇒ identical decision), and the
  documented **restore anchor** (measured from the effective-end reference, not an
  archival timestamp — with and without `effective_to`).
- `test_adversarial.py` — control/NUL/CR-LF/bidi and empty/whitespace identifier
  rejection across entity ids and metadata (legitimate Arabic/accented-Latin/CJK
  preserved), extreme version numbers and retention-day bounds, the oversized-chain
  bound, immutability of decision/policy/report models, unknown-field rejection,
  and the exported `ensure_safe_label` helper.
- `test_performance.py` (review fix) — a **deep legal linear chain** (N = 8000,
  within `MAX_CHAIN_SIZE = 10_000`) whose construction + `validate_chain` must
  finish under a generous 5 s ceiling (the old O(N²) implementation needed
  ~25–40 s; the O(N) implementation clears it in tens of ms), a full deep-lineage
  walk, and a no-recursion-limit-dependence check.
- **`require_reason` enforcement** (in `test_validation.py`) — `validate_event` /
  `assert_event` with `require_reason=True` (reason present → ok; reason absent →
  `MissingReasonError`), whitespace-only reason rejected at event construction,
  `require_reason=False` without a reason ok, a policy-disabled transition on an
  event, and deterministic output. Plus the reachable `INVALID_STATE` issue (via
  `model_construct`) and deterministic issue ordering — so no validation branch is
  pragma-only dead code.
- **Typed unknown-lineage error** (in `test_chain.py`) — `VersionChain.lineage()`
  raises `emg_errors.NotFoundError` for an id not in the chain.
- `test_import.py` — version, the named public surface, and a clean-subprocess
  assertion that **no storage/network/AI module** and **no sibling Module-7
  package** (`emg_ontology`, `emg_knowledge_pipeline`, `emg_trust_scoring`,
  `emg_semantic_layer`) is imported by the library.

The **Module 6 golden audit-hash** and the **Sprint 9 golden ontology
descriptor** regressions run unchanged; FEAT-05-5 is a new isolated library that
touches no Module 1–6 code, record, or hash, does not modify `emg-ontology`,
`emg-knowledge-pipeline`, `emg-trust-scoring`, or `emg-semantic-layer`, and is not
wired into any service this sprint.

## Universal Connector Framework testing (Sprint 14, EPIC-13 / FEAT-13-1)

`libs/python/emg-connectors/tests` — pure unit tests (no Docker, no database, no
service, no network; the framework is contracts-only and executes nothing). Test
doubles are neutral fakes in `_helpers.py` (no vendor, no I/O); the library ships
no connector.

- `test_version.py` — semantic-version parse/compare/`is_compatible_with`,
  `VersionRange.contains`, inverted-range rejection, immutability.
- `test_capabilities.py` — capability set normalisation (sorted-unique,
  deterministic), support helpers, capability **negotiation** (satisfied + every
  missing dimension), determinism, the `CapabilityRegistry` feature-discovery
  catalogue, and **extensible vendor capabilities** (`extension_capabilities`
  supported alongside standard, sorted-unique normalisation, may-not-reuse-a-
  standard-value, control/bidi rejection, extension negotiation + determinism).
- `test_configuration.py` — schema/field validation, **configuration validation**
  against a schema (missing-required, type mismatch, unknown key, bool-not-int,
  secret-must-be-string), duplicate-field rejection, value immutability, and the
  **authentication contract** (opaque credential reference; `none` vs non-`none`
  rules) — asserting no raw secret is modelled.
- `test_lifecycle.py` — the connector and plugin transition tables as **golden
  sets**, no self-transitions, terminal `retired`, and typed rejection.
- `test_registry_factory.py` — **registry** register/get/duplicate/unknown/
  unregister/deterministic-order and **factory** create/compatibility/unknown-id/
  identity-mismatch.
- `test_plugin.py` — plugin-descriptor validation, `PluginValidation` (coherence),
  `PluginCompatibility` (version range), and the in-memory `ConnectorPluginLoader`
  (register/enable, duplicate, incompatible, unregister, lifecycle transitions).
  Also covers the loader as **single source of truth**: registering a plugin
  **auto-publishes** its connectors (no separate registry call), unregistering
  **withdraws** them (plugin-removal consistency, no drift), cross-plugin
  `connector_id` collisions are rejected **atomically** (no partial state), and two
  loaders keep **independent** connector state.
- `test_discovery.py` — discovery by capability/entity-type/vendor/sync-mode/auth
  and by full requirement (negotiation); deterministic results.
- `test_synchronization.py` — sync **contracts** (incremental requires cursor),
  **policy** bounds, full/incremental **plan** mode validation, and
  `ConnectorValidator.validate_synchronization`.
- `test_models.py` — descriptor helpers, health/statistics/status, events/change/
  snapshot, `AbstractConnector` lifecycle+status, mapper protocols (structural),
  and nested-mapping immutability.
- `test_adversarial.py` — control/NUL/CR-LF/bidi and empty/whitespace identifier
  rejection (legitimate Unicode preserved), attribute-key validation, input-dict
  non-aliasing, oversized-collection bounds, extreme version numbers,
  unknown-field rejection, determinism.
- `test_import.py` — version, the full public surface, a clean-subprocess
  **dependency-direction / forbidden-technology** check (no networking/SDK/sibling
  module is imported), and a **no-vendor-branching guard** that strips strings and
  comments from every core module and asserts no vendor token appears in
  executable code.

The **Module 6 golden audit-hash** and **Sprint 9 golden ontology descriptor**
regressions run unchanged; FEAT-13-1 is a new isolated library that touches no
Module 1–6 code, record, or hash, does not modify any sibling library, and is not
wired into any service this sprint.
