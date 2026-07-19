# emg-persistence

**EMG Persistence Binding — Phase 2.** Durable `GraphStore` adapters for the
Enterprise Memory Graph, behind the unchanged Phase 1 `GraphStore` port.

Architecture (approved `PHASE2_ARCHITECTURE.md` Revision 3):

- **PostgreSQL is the authoritative** revision log + head pointer (ADR-1). The
  write open/commit path and the read fallback use PostgreSQL only (ADR-5).
- **Neo4j is a rebuildable serving projection** — never on the write path.

## Sprint 1 scope (this delivery)

Only the package **scaffold**:

- `config.py` — `PersistenceSettings` (pydantic-settings): datastore DSNs and
  pool/timeout knobs, read from the environment.
- `factory.py` — `build_graph_store(settings)`: the dependency-injection seam.
  With no datastore configured it returns the Phase 1 `InMemoryGraphStore`
  (dev/tests); the persistent `PostgresNeo4jGraphStore` is wired in later
  sprints.
- `errors.py` — the typed error hierarchy (`PersistenceError`,
  `PersistenceConflictError`, `ProjectionLagError`).

## Not in Sprint 1 (later sprints)

No PostgreSQL/Neo4j code, no schema, no migrations, no repositories, no
`GraphStore` implementation, no SQL/Cypher. Those arrive in Sprints 2–8 per
`PHASE2_PLAN.md`. Database drivers (`neo4j`, `psycopg`) are therefore **not** yet
declared as dependencies — they are added in the sprint that first uses them, to
avoid unused dependencies.
