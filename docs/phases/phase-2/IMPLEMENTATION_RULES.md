# IMPLEMENTATION_RULES.md

**Status:** MANDATORY ENGINEERING CONTRACT

**Governing Authority:** Phase 2 Architecture Revision 3

**Target Audience:** All Engineering Personnel contributing to the EMG™ Core Platform

---

## Architectural Invariants

The following permanent rules form the core foundation of the platform and must never be altered or bypassed by any engineer under any circumstances:

* **PostgreSQL is the Only Source of Truth:** All system durability, revision tracking, history logs, outbox entries, and transactional boundaries are strictly owned by PostgreSQL.
* **Neo4j is Disposable:** Neo4j functions strictly as a query-optimized topology map to support fast traversals and lookups. It owns no authoritative records and can be completely wiped and recompiled directly from the PostgreSQL revision log at any time.
* **Append-Only Revision History:** All graph mutations must be stored as an immutable, forward-moving chain of historical events. Destructive updates or overwrites to past graph states are completely prohibited.
* **Immutable Revisions:** Once a revision record is appended and committed to PostgreSQL, its properties, metadata, and contents can never be altered or updated.
* **Optimistic Concurrency (CAS):** Head modification updates require precise pointer matching against the expected revision counter to prevent race conditions and lost updates across processes.
* **Snapshot Immutability:** Every raw graph representation (`graph_json`) preserved within the log must remain completely frozen as it existed at the exact moment of its commit.
* **Exactly One Outbox Event Per Committed Revision:** Every completed revision change must generate exactly one `graph.revision.committed` notification entry; granular node/edge changes are excluded from this layer.
* **Never Bypass GraphStore:** The `GraphStore` protocol governs all high-level multi-tenant storage interactions. No calling service may open direct database connections that circumvent this entrypoint.
* **Never Bypass RevisionRepository:** The `RevisionRepository` encapsulates the atomic compare-and-set database mechanics. Circumventing this boundary layer to access low-level tables directly is barred.
* **No Cross-Layer Dependencies:** To ensure long-term stability and prevent regression, dependencies must flow in a strict, un-directed outward model. Circular relationships between system layers are strictly barred.
* **Bilingual Foundation (ADR-018):** Arabic and English are first-class. Persistence must preserve UTF-8 bilingual payloads in `graph_json` / projection `content_json` without stripping language content. Domain multilingual enrichment is mandatory in later phases; Phase 2 guarantees opaque preservation and hash-stable reconstruction.

---

## 1. Project Principles

### PostgreSQL is the Single Authoritative Source of Truth (Phase 2 Architecture Revision 3)

* **Explanation:** All system durability, revision tracking, history logs, outbox entries, and transactional boundaries are strictly owned by PostgreSQL. No operation is considered successful or permanent until it is successfully committed inside PostgreSQL.
* **Operational Directive:** If PostgreSQL is down, the entire system must reject mutations and fail closed. No fallback storage medium can grant write operations authority.

### Neo4j is a Serving Projection Only (Phase 2 Architecture Revision 3)

* **Explanation:** Neo4j functions strictly as a query-optimized topology map to support fast traversals and lookups. It owns no authoritative records and can be completely wiped and recompiled directly from the PostgreSQL revision log at any time.
* **Operational Directive:** Neo4j is entirely decoupled from the transactional write open and commit paths. A mutation must succeed even if Neo4j is completely unavailable.

### Strict Architectural Preservation

* **Explanation:** The design baseline established in `PHASE2_ARCHITECTURE.md` Revision 3 is frozen. Engineers are forbidden from modifying structural boundaries, changing transaction scopes, or re-engineering data flows.
* **Operational Directive:** Your role is strict, high-fidelity execution of the approved specifications. Optimization or alteration of structural layers without formal change control is a breach of contract.

### Never Bypass Core Abstractions (`GraphStore` / `RevisionRepository`)

* **Explanation:** The `GraphStore` protocol governs all high-level multi-tenant storage interactions, while `RevisionRepository` encapsulates the atomic compare-and-set database mechanics.
* **Operational Directive:** No service, application, or script may open direct database sessions or execute raw queries that circumvent these repositories. All persistence data interactions must flow through their designated boundary ports.

### Zero Hidden Persistence and Out-of-Band State

* **Explanation:** The system strictly prohibits hidden side effects, background threads creating implicit transactions, or untracked state transformations. Every modification must be explicit, trackable, and bounded.
* **Operational Directive:** Per Phase 2 Architecture Revision 3, `GraphStore.write()` must execute all authoritative operations completely within its transaction window and perform absolutely zero post-return background execution.

### Strict Layer Isolation and Dependency Direction

* **Explanation:** To ensure long-term stability and prevent regression, dependencies must flow in a strict, un-directed outward model. Inner domain frameworks must remain decoupled from specific infrastructure details.
* **Operational Directive:** Circular relationships are strictly barred. An inner module (e.g., `emg-memory-graph`) must never import or possess awareness of an outer layer (e.g., `emg-persistence`).

---

## 2. Layer Responsibilities

### Core Domain (`libs/python/emg-memory-graph`, `libs/python/emg-ontology`)

* **Purpose:** Defines the foundational immutable domain structures, business objects, state types, and pure ontology specifications.
* **Responsibilities:** Implements structural data objects, provides self-contained schema validators, and exposes the pure deterministic `content_hash()` logic.
* **Forbidden Responsibilities:** Must not perform any I/O, connect to databases, process configuration environments, manage multi-tenant routing, or maintain stateful network pools.
* **Dependencies:** Only references basic structural types and pinned foundational packages (`pydantic`, `emg-common-types`, `emg-errors`).

### Persistence (`libs/python/emg-persistence`)

* **Purpose:** Manages the physical lifecycle, atomicity, durability, and storage-mapping operations of the system.
* **Responsibilities:** Implements the concrete `GraphStore` interface, manages PostgreSQL connection pooling, drives the custom migration engine, and coordinates compare-and-set boundaries. The persistence package contains the infrastructure required for the transactional outbox, but the actual Outbox implementation belongs exclusively to the specific Sprint defined in `PHASE2_PLAN.md`. Sprint 4 must not imply that the Outbox is already implemented. Neo4j driver dependencies are used exclusively by the projection subsystem; Sprint 4 must not communicate with Neo4j, and Neo4j must never participate in the authoritative PostgreSQL transaction.
* **Forbidden Responsibilities:** Must not alter domain entity properties, enforce user interface workflows, or embed query-routing presentation mechanics.
* **Dependencies:** Implements `emg-platform-core` ports, imports `emg-memory-graph` models, and handles underlying drivers (`psycopg`, `neo4j`).

### Semantic Layer (`libs/python/emg-semantic-layer`)

* **Purpose:** Implements storage-independent, deterministic query, traversal, and graph projection models.
* **Responsibilities:** Compiles logical queries into structured step plans, manages bounded parameters, and defines the uniform query surface for external clients.
* **Forbidden Responsibilities:** Must not open direct connections to physical datastores, execute database-specific query syntax, or orchestrate mutations.
* **Dependencies:** Depends strictly on `emg-common-types`, `emg-errors`, and basic domain schema modules.

### Services (`/services/*`)

* **Purpose:** Functional runtime execution contexts providing bounded application logic via network application boundaries.
* **Responsibilities:** Exposes authenticated network boundaries (e.g., identity, audit), handles protocol transformations, handles basic cross-library orchestration, and provisions service entrypoints.
* **Forbidden Responsibilities:** Must not contain raw database mapping schemas or encapsulate core domain operations outside of their underlying library bindings.
* **Dependencies:** Consumes the validated `/libs` packages and standard infrastructure client wrappers.

### Apps (`/apps/*`)

* **Purpose:** Houses high-level user interfaces and Backend-for-Frontend (BFF) layers.
* **Responsibilities:** Manages user session presentations, coordinates client-facing API responses, and formats outward visual payloads.
* **Forbidden Responsibilities:** Strictly barred from executing business rules, modifying trust algorithms, or maintaining low-level database operations.
* **Dependencies:** Communicates over clean network APIs via the exposed service layer.

### Infrastructure (`/infra`)

* **Purpose:** Automates environment topologies and continuous deployment resource bindings.
* **Responsibilities:** Configures service orchestration targets, declares network policies, and provisions container topologies.
* **Forbidden Responsibilities:** Must not contain application code or inject local business mutations.
* **Dependencies:** Operates independently of internal code, referencing target configuration specs.

### Observability (`/observability`)

* **Purpose:** Controls platform transparency, diagnostic indexing, performance analysis, and alerting systems.
* **Responsibilities:** Standardizes diagnostic log processing formats, exposes health checks, and builds uniform monitoring configurations.
* **Forbidden Responsibilities:** Must not modify database state or act as an execution pathway for domain logic.
* **Dependencies:** Integrates downstream monitoring targets via standardized data pipes.

---

## 3. Sprint Development Rules

### Structural Preservation and Scope Isolation

* **Directive:** Engineers are strictly confined to the defined bounds of the active Sprint. Modifying code built in previous Sprints to introduce unapproved behavioral adjustments is prohibited.
* **Execution:** Do not add forward-looking optimizations, speculative abstractions, or hidden capabilities designed to solve problems slated for future milestones. Implement the explicit tasks defined in the design documents.

### Zero Tolerance for Stubs or Partial Work

* **Directive:** All implementations committed to the codebase must be functional, complete, and production-grade within the scope of the sprint.
* **Execution:** Code submissions containing `TODO`, `FIXME`, or `XXX` comment markers will be automatically rejected at the pull request phase. Mock implementations or stubbed methods designed to bypass actual feature delivery are barred.

---

## 4. File Ownership

### Packages: `libs/python/emg-persistence`

#### Files Allowed to be Modified (Per Active Sprint Plan)

* `src/emg_persistence/config.py` (Adding verified setting entries)
* `src/emg_persistence/factory.py` (Wiring concrete storage classes)
* `src/emg_persistence/store.py` (Updating persistence adapter structures)
* `src/emg_persistence/postgres/*.py` (Extending internal repository access patterns)
* `src/emg_persistence/neo4j/*.py` (Adjusting projection mapping mechanics)

#### Files That Must Never Change

* All foundational structures in `libs/python/emg-memory-graph/src/`
* Pinned ontology structures inside `libs/python/emg-ontology/src/`
* Existing baseline contracts in `libs/python/emg-platform-core/`

#### Files Requiring Architecture Review Before Modification

* `src/emg_persistence/migrate.py` (Core migration runner engine)
* `src/emg_persistence/migrations/postgres/V001__baseline.sql` (Authoritative database tables schema)
* `src/emg_persistence/migrations/neo4j/M001__constraints.cypher` (Projection constraints schema)

---

## 5. Coding Standards

### Python Style & Strict Typing

* **Style:** Strict adherence to PEP 8 standards enforced via `ruff` and `black` layout formatters.
* **Typing:** Strict typing via `mypy --strict` is non-negotiable. Every parameter, return type, and class variable must be explicitly annotated. Type escapes like `Any` or `# type: ignore` annotations require a documented justification and are subject to rejection. Classes must include `py.typed` markers.

### Exception Hierarchy and Handling

* **Structure:** All exceptions generated within the storage layer must derive explicitly from `PersistenceError`, extending outward from the platform baseline `emg_errors.EMGError`.
* **Catching Strategy:** Never allow database-specific driver exceptions (`psycopg.Error`, `neo4j.exceptions.DriverError`) to leak past the persistence layer boundary. Wrap all underlying engine anomalies cleanly into structural system exceptions:

```python
try:
    # Database interaction
except psycopg.errors.SerializationFailure as err:
    raise PersistenceConflictError("Optimistic lock failure on head modification") from err
except psycopg.Error as err:
    raise PersistenceError("Database operation anomaly occurred") from err

```

### Logging Conventions

* **Directives:** Log structural events using contextual, structured key-value configurations. Do not write plaintext string lookups.
* **Constraints:** Under no circumstances may sensitive values, multi-tenant authentication keys, or internal PII cleartext be logged.

### Dependency Injection, Interfaces, and Factories

* **Strategy:** Decouple object assembly from business pathways via standard structural factories.
* **Execution:** System components must depend strictly on structural interface contracts or Python `Protocols`. The initialization logic within `factory.py` parses configuration properties (`PersistenceSettings`) to return the target implementation dynamically.

---

## 6. Database Rules

### PostgreSQL Execution Rules

* **Atomicity Limits:** All operations that modify state within a single `write()` request must execute within one explicit transaction block.
* **Lock Management:** Keep transaction hold times short. Head evaluations on no-op pathways must use either `SELECT ... FOR UPDATE` or `SELECT ... FOR KEY SHARE` where appropriate under Phase 2 Architecture Revision 3 to enable safety while preventing stale read scenarios. Do not use `FOR SHARE`.

### Neo4j Projection Rules

* **Mutation Limits:** Direct, structural raw modifications to Neo4j that bypass the primary PostgreSQL pipeline are strictly forbidden.
* **Cypher Formatting:** Every Cypher execution loop must be parameterized. Relationship mappings, node creation updates, and projection changes must enforce idempotent operations using `MERGE` and `DELETE` steps.

### Migration Hardening Rules

* **Verification Logic:** The migration execution pipeline (`migrate.py`) must record every schema shift inside `schema_migrations` alongside an immutable SHA-256 file signature.
* **Fault Handling:** If an operational error occurs or a script exits abnormally mid-migration, the system state must be marked as dirty and block subsequent startup loops until manually cleared.

### Concurrency and Compare-and-Set Mechanics

* **Validation Bounds:** Upward state adjustments for the tenant head require exact tracking checks:

$$\text{WHERE head\_revision\_number} = R_0$$


* **Conflict Handling:** If an update returns zero affected rows, the system must trigger a `PersistenceConflictError` to rollback changes safely. First-revision synchronization must be explicitly managed through `INSERT ... ON CONFLICT (tenant_id) DO NOTHING` declarations.

### Serialization & Semantic Equality

* **Snapshot Preservation:** Every revision record must retain the complete serialized graph payload (`graph_json`) to ensure instant O(1) retrieval capabilities during fallback execution paths.
* **Equality Invariant:** Graph validation checks assess structural completeness via canonical semantic verification signatures (`reconstructed.content_hash() == authoritative_revision.content_hash`) rather than evaluating raw byte similarities, protecting the layer from serialization drift across dependencies.

---

## 7. Testing Rules

### Testing Layout Matrix

* **Unit Tests:** Located in `tests/`. Validates configuration constraints, basic factory parsing, exception mappings, and logic states without hitting real database connections.
* **Integration Tests:** Located in `tests/integration/`. Validates end-to-end repository code against real, ephemeral PostgreSQL and Neo4j database containers.
* **Contract Tests:** Located in `tests/contract/`. Reuses and runs the uniform Phase 1 test suite to guarantee the persistent adapter behaves identically to the in-memory reference engine.

### Concurrency and Adversarial Testing

* **Requirements:** Multi-threaded integration sweeps must intentionally introduce racing conditions, concurrent first-revision creation calls, and head collision scenarios. The execution paths must prove that concurrent operations resolve deterministically without causing corrupt states, double outbox processing, or stale read results.

### Quality Gates and CI Standards

* **Coverage Matrix:** The concrete storage library package requires an overall line coverage target of **>95%**.
* **CI Invariants:** The `persistence` execution pipeline must execute the complete database test suite against standard PostgreSQL 16 and Neo4j 5 Community Edition configurations. All quality inspections (`ruff`, `black --check`, `mypy --strict`) must return completely clean results for code promotion.

---

## 8. Performance Rules

### Database Access Profiles

* **Directives:** Limit database queries inside loop scopes. Batch structural node updates using parameterized array bindings.
* **Execution Bounds:** Connection scopes must follow pool parameters defined in configuration settings. Do not leave un-returned sessions open beyond functional block windows.

### Memory Constraints and Allocation Boundaries

* **Directives:** Stream large query operations using clean cursor bindings instead of caching deep record histories within operational system memory.
* **Execution Bounds:** Because the `GraphStore` deserializes localized snapshot files into working single-tenant instances, lookups must verify payload sizes conform to performance specifications.

### Serialization, Hashing, and Networking

* **Directives:** Minimize JSON transformations across transactional code blocks. Leverage optimized, pre-compiled serialization engines.
* **Execution Bounds:** Component hashing loops must utilize the standardized, deterministic graph evaluation algorithms implemented in `emg-memory-graph`. Do not build ad-hoc crypto procedures at the database boundary.

---

## 9. Security Rules

### Multi-Tenant Scoping and Separation

* **Directives:** Cross-tenant leakage is a Critical (P0) system failure. Every data lookup statement must filter parameters using an explicit, validated `tenant_id` context.
* **Execution Bounds:** Data queries that omit explicit tenant criteria will fail code reviews. The integration testing suites must include specific verification paths to confirm that cross-tenant data requests are rejected.

### Injection Defense Engineering

* **SQL Injection Prevention:** Every dynamic parameter value passed to PostgreSQL must evaluate through proper query binding mechanics. String concatenation and raw interpolation within query statements are strictly banned.
* **Cypher Injection Prevention:** Every variable passed down to the Neo4j engine must use explicit parameter mappings. Ensure that structural identifiers (e.g., node type flags, keys) are validated against structural allowlists before engine execution.

---

## 10. Forbidden Changes

* **NEVER** include Neo4j modifications inside the authoritative PostgreSQL write transaction path (Violates Phase 2 Architecture Revision 3).
* **NEVER** mark a write transaction as successful if the underlying PostgreSQL commit fails or is aborted (Violates Phase 2 Architecture Revision 3).
* **NEVER** attach a unique constraint onto the `content_hash` column inside the `graph_revisions` log schema (Violates Phase 2 Architecture Revision 3).
* **NEVER** instantiate background processing routines or detached worker processes within the standard context of `GraphStore.write()` (Violates Phase 2 Architecture Revision 3).
* **NEVER** bypass the custom migration execution pipeline to perform direct, manual schema adjustments to production database instances.
* **NEVER** pass raw string formats containing un-sanitized user parameters to database query executors.
* **NEVER** modify single-tenant domain structures in `emg-memory-graph` to maintain multi-tenant state handling (Violates D1).
* **NEVER** alter the contract parameters or public interfaces of the `GraphStore` port defined during Phase 1.
* **NEVER** permit structural driver errors to escape the storage boundary layer without conversion into platform exception types.
* **NEVER** publish multiple outbox messages for a single revision commit event (Violates Outbox contract).
* **NEVER** add business routing decisions, authorization evaluations, or domain validation rules into storage repository components.
* **NEVER** write code blocks that rely on byte-level matches to verify structural correctness across system layers.

---

## 11. Definition of Done

A Sprint milestone or feature change is considered officially **DONE** when it satisfies all of the following criteria:

* **Architecture Compliance:** Code structure conforms exactly to the specifications in `PHASE2_ARCHITECTURE.md` Revision 3; all platform design mandates are fully met.
* **Documentation:** Operational manuals, running guides, system charts, and the final `PHASE2_COMPLETION.md` performance reports are finalized and reviewed.
* **Unit Tests:** Code blocks pass localized test validations with no external database requirements.
* **Integration Tests:** Storage workflows pass integration validation across real PostgreSQL and Neo4j testing environments.
* **Type Checking:** Standard compilation checks return completely clean runs using `mypy --strict`.
* **Formatting & Linting:** Formatting checks execute cleanly via `ruff` and `black` scripts with zero code errors.
* **CI Execution:** The complete continuous integration pipeline passes successfully, including the custom `persistence` job container validations.
* **Performance Budget Validation:** Storage lookups and modification latencies fall within the platform's performance boundaries.
* **Backward Compatibility:** Phase 1 integration behaviors are preserved; the core port layer remains compatible with existing applications.

---

## 12. Engineering Checklist

Before submitting a Pull Request for architectural review, ensure you can check **YES** to every item below:

* [ ] Does the implementation leave all Phase 1 public port interfaces completely intact and free of breaking changes?
* [ ] Have you confirmed that Neo4j is excluded from the critical path of the write transaction open and commit sequences?
* [ ] Does your code ensure that `GraphStore.write()` executes entirely within its immediate context, initiating absolutely zero background threads or asynchronous post-return workers?
* [ ] Have you verified that the `content_hash` database tracking column is configured without a UNIQUE constraint?
* [ ] Does the no-op write execution sequence explicitly revalidate the authoritative PostgreSQL head using `FOR UPDATE` or `FOR KEY SHARE` before returning its completion receipt?
* [ ] Does the read execution path include a functional fallback routing mechanism to retrieve data directly from PostgreSQL if Neo4j is offline?
* [ ] Have you verified that all database interaction routines use parameterized inputs with no direct string interpolation?
* [ ] Does the workspace return a completely clean compilation report when executing `make typecheck` (`mypy --strict`)?
* [ ] Do local quality checks (`make lint`) pass cleanly without requiring custom style overrides or code bypass rules?
* [ ] Does the system test suite achieve an overall line coverage result of over 95% across the modified package codebase?
* [ ] Have you verified that the transactional outbox system registers exactly one message per completed revision update?
* [ ] Are all code comments free of `TODO`, `FIXME`, or placeholder markers?
