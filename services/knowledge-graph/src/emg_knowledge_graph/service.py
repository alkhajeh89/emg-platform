"""Application-service boundary for Module 7 orchestration."""

from __future__ import annotations

from emg_platform_core.ports import GraphStore


class KnowledgeGraphApplication:
    """Application/orchestration layer over the platform GraphStore boundary."""

    def __init__(self, graph_store: GraphStore) -> None:
        self._graph_store = graph_store
