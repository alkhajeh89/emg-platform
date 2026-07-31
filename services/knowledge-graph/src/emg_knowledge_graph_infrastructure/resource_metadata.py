"""Read-only graph adapter for ADR-027 authorization preflight metadata."""

from __future__ import annotations

from emg_knowledge_graph import IResourceMetadataReader, ResourceMetadata
from emg_platform_core import TenantId
from emg_platform_core.ports import GraphStore


class GraphResourceMetadataReader(IResourceMetadataReader):
    """Project only authorization metadata from the current immutable graph."""

    def __init__(self, graph_store: GraphStore) -> None:
        self._graph_store = graph_store

    def read_entity(self, tenant: TenantId, entity_id: str) -> ResourceMetadata | None:
        node = self._graph_store.read(tenant).node(entity_id)
        if node is None:
            return None
        return ResourceMetadata(
            resource_type="knowledge-graph.entity",
            resource_id=node.node_id,
            classification=node.classification,
            owner=node.owner or None,
        )

    def read_relationship(self, tenant: TenantId, relationship_id: str) -> ResourceMetadata | None:
        edge = self._graph_store.read(tenant).edge(relationship_id)
        if edge is None:
            return None
        return ResourceMetadata(
            resource_type="knowledge-graph.relationship",
            resource_id=edge.edge_id,
            classification=edge.classification,
            owner=None,
            source_id=edge.source_id,
            target_id=edge.target_id,
        )
