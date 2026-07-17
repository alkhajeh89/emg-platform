"""Import + version + public-surface tests (FEAT-05-2)."""

from __future__ import annotations

import emg_knowledge_pipeline as kp


def test_version() -> None:
    assert kp.__version__ == "0.1.0"


def test_public_surface_exported() -> None:
    for name in (
        "EntityIngestionRequest",
        "RelationshipIngestionRequest",
        "IngestionBatch",
        "IngestionContext",
        "InMemoryGraphStore",
        "GraphStore",
        "GraphTransaction",
        "KnowledgePipeline",
        "IngestionResult",
        "validate_and_build",
        "build_mutation_event",
        "IngestionValidationError",
        "GraphPersistenceError",
    ):
        assert hasattr(kp, name), name


def test_in_memory_store_satisfies_graph_store_protocol() -> None:
    store = kp.InMemoryGraphStore()
    assert isinstance(store, kp.GraphStore)
    assert isinstance(store.begin(), kp.GraphTransaction)
