# services/knowledge-graph

Scaffolded in Sprint 1 (FEAT-01-1). Governing architecture: Module 7 — Knowledge
Graph Platform. No business logic or API implementation exists yet — see
/services/README.md for target Epic/Sprint.

## Boundary scope

`services/knowledge-graph` is an application/orchestration boundary.
Graph-domain models and behavior belong to `emg-memory-graph`.

Tenant-scoped graph persistence is accessed through the platform-core
`emg_platform_core.ports.graph_store.GraphStore` port. Persistence adapters stay
behind `emg-persistence`.

This task introduces no public API surface and implements no graph reads,
writes, or queries.
