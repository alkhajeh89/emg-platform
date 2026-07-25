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

The internal `KnowledgeGraphApplication.build_revision()` workflow accepts
validated ontology objects plus an explicit tenant, principal, and `as_of`
timestamp. It extends the tenant's current immutable graph through
`MemoryGraphBuilder` and commits through the platform `GraphStore` transaction.
The returned `BuildRevisionResult` is an immutable application DTO whose tenant,
principal, content hash, and graph counts are copied from the committed
`WriteReceipt`; the storage receipt itself is not exposed.
It is not an HTTP or production-ingress API; mutation-audit reconciliation
remains a prerequisite for production enablement under ADR-022.
