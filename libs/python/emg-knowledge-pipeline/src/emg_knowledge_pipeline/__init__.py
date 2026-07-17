"""emg_knowledge_pipeline — the Knowledge Ingestion Pipeline (Module 7 —
Knowledge Graph Platform, EPIC-05, FEAT-05-2). Added Sprint 10.

Library-first and **storage-independent**: it converts validated
`emg-ontology` models into persistent graph operations through a `GraphStore`
abstraction, so a Neo4j adapter can be added later (FEAT-05-4) without changing
ingestion logic. It reuses the completed EPIC-04 Audit Platform
(`emg-audit-client`) to emit graph-mutation audit contracts — never a parallel
record.

Out of scope for Sprint 10 (deliberately): the Neo4j binding, retrieval,
semantic search, embeddings, AI, UI, trust-score calculation (FEAT-05-3), the
semantic layer (FEAT-05-4), and lifecycle management (FEAT-05-5).
"""

from .audit import build_mutation_event, mutation_event_id, provenance_reference_for
from .context import IngestionContext, SourceType
from .errors import (
    GraphPersistenceError,
    IngestionConflictError,
    IngestionError,
    IngestionProblem,
    IngestionValidationError,
)
from .graph_store import (
    GraphStore,
    GraphTransaction,
    InMemoryGraphStore,
    InMemoryGraphTransaction,
)
from .idempotency import entity_id_for, mutation_event_id_for, relationship_id_for
from .pipeline import CollectingAuditSink, KnowledgePipeline
from .requests import (
    MAX_ATTRIBUTE_VALUE_LEN,
    MAX_ATTRIBUTES,
    MAX_BATCH_ENTITIES,
    MAX_BATCH_RELATIONSHIPS,
    MAX_NATURAL_KEY_LEN,
    EntityIngestionRequest,
    IngestionBatch,
    RelationshipIngestionRequest,
)
from .resolver import (
    resolve_entity_id,
    resolve_relationship_endpoints,
    resolve_relationship_id,
)
from .result import IngestionResult
from .validation import ACYCLIC_RELATIONSHIP_TYPES, ValidatedBatch, validate_and_build

__version__ = "0.1.0"

__all__ = [
    # requests + context
    "EntityIngestionRequest",
    "RelationshipIngestionRequest",
    "IngestionBatch",
    "IngestionContext",
    "SourceType",
    "MAX_NATURAL_KEY_LEN",
    "MAX_ATTRIBUTE_VALUE_LEN",
    "MAX_ATTRIBUTES",
    "MAX_BATCH_ENTITIES",
    "MAX_BATCH_RELATIONSHIPS",
    # idempotency + resolvers
    "entity_id_for",
    "relationship_id_for",
    "mutation_event_id_for",
    "resolve_entity_id",
    "resolve_relationship_endpoints",
    "resolve_relationship_id",
    # graph store + transactions
    "GraphStore",
    "GraphTransaction",
    "InMemoryGraphStore",
    "InMemoryGraphTransaction",
    # validation
    "validate_and_build",
    "ValidatedBatch",
    "ACYCLIC_RELATIONSHIP_TYPES",
    # audit
    "build_mutation_event",
    "provenance_reference_for",
    "mutation_event_id",
    # pipeline + result
    "KnowledgePipeline",
    "CollectingAuditSink",
    "IngestionResult",
    # errors
    "IngestionError",
    "IngestionValidationError",
    "IngestionConflictError",
    "GraphPersistenceError",
    "IngestionProblem",
    "__version__",
]
