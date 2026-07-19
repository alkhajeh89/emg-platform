// EMG Persistence — Neo4j serving-projection schema (Phase 2, M001).
// Neo4j is a rebuildable serving projection (ADR-1), never on the write path.
// Declarative structure only. Every statement is idempotent (IF NOT EXISTS) so
// re-running is safe (Neo4j has no transactional DDL). Community-Edition
// compatible (uniqueness constraints + indexes only; no enterprise-only
// node-key / relationship-key constraints).

CREATE CONSTRAINT memory_node_identity IF NOT EXISTS
FOR (n:MemoryNode) REQUIRE (n.tenant_id, n.node_id) IS UNIQUE;

CREATE CONSTRAINT graph_head_tenant IF NOT EXISTS
FOR (h:GraphHead) REQUIRE h.tenant_id IS UNIQUE;

CREATE INDEX memory_node_type IF NOT EXISTS
FOR (n:MemoryNode) ON (n.tenant_id, n.node_type);

CREATE INDEX memory_edge_identity IF NOT EXISTS
FOR ()-[e:MEMORY_EDGE]-() ON (e.tenant_id, e.edge_id);
