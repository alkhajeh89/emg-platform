"""Enterprise Memory Graph Core Engine (Module 7 — Knowledge Graph, EPIC-05,
FEAT-05-6).

Transforms the structured knowledge objects produced by ingestion + lifecycle
into a persistent, temporal, evidence-linked, versioned graph of entities,
relationships, evidence, observations and decisions. Deterministic, immutable,
storage-independent; composes the existing platform libraries without duplicating
them (see `docs/engineering/memory-graph-architecture.md`).
"""

from __future__ import annotations

__version__ = "0.1.0"

# --- foundations -------------------------------------------------------------
from .builder import BuildResult, EdgeInput, MemoryGraphBuilder, NodeInput
from .confidence import ConfidenceAssessment, ConfidenceEngine, ConfidencePolicy
from .edges import MemoryEdge
from .enums import (
    ConfidenceBand,
    EdgeDirection,
    EdgeType,
    EvidenceSource,
    MatchType,
    MemoryNodeType,
)
from .errors import (
    EdgeNotFoundError,
    EvidenceRequiredError,
    MemoryGraphError,
    MergeConflictError,
    NodeNotFoundError,
    ResolutionError,
    RevisionError,
    TemporalConsistencyError,
    TraversalLimitError,
)

# --- core models -------------------------------------------------------------
from .evidence import EvidenceRef
from .graph import EMPTY_GRAPH, MemoryGraph
from .ids import edge_id_for, evidence_id_for, node_id_for, revision_id_for
from .labels import SafeLabel, SafeText, ensure_safe_label
from .limits import (
    MAX_EVIDENCE_REFS,
    MAX_LINEAGE_DEPTH,
    MAX_METADATA_ENTRIES,
    MAX_PATH_RESULTS,
    MAX_SUPERSEDES,
    MAX_TRAVERSAL_DEPTH,
)
from .lineage import DecisionLineage, LineageEdgeRef, LineageNode, LineagePath, LineageTrace
from .metadata import EMPTY_METADATA, Metadata, MetadataItem
from .nodes import MemoryNode
from .projection import (
    MemoryGraphExecutor,
    to_semantic_graph,
    to_semantic_node,
    to_semantic_relationship,
)
from .query import MemoryQueryEngine, PathResult, RelatedNode

# --- engines -----------------------------------------------------------------
from .resolution import (
    EntityMention,
    EntityResolver,
    ResolutionConfig,
    ResolutionResult,
    ResolvedEntity,
    Resolver,
    normalize_label,
)
from .search import (
    MAX_SEARCH_QUERY_BYTES,
    MAX_SEARCH_QUERY_SCALARS,
    SEARCH_NORMALIZER_VERSION,
    normalize_search_text,
)
from .temporal import TemporalFact, TemporalHistory, TemporalValidity
from .temporal_query import (
    active_edges_at,
    attribute_at,
    neighbors_at,
    node_exists_at,
    subgraph_as_of,
)
from .versioning import (
    EMPTY_HISTORY,
    GraphDiff,
    GraphHistory,
    GraphRevision,
    diff_graphs,
)

__all__ = [
    # enums
    "MemoryNodeType",
    "EdgeType",
    "EvidenceSource",
    "MatchType",
    "EdgeDirection",
    "ConfidenceBand",
    # errors
    "MemoryGraphError",
    "NodeNotFoundError",
    "EdgeNotFoundError",
    "EvidenceRequiredError",
    "MergeConflictError",
    "TemporalConsistencyError",
    "ResolutionError",
    "TraversalLimitError",
    "RevisionError",
    # labels / limits / metadata
    "SafeLabel",
    "SafeText",
    "ensure_safe_label",
    "MAX_EVIDENCE_REFS",
    "MAX_METADATA_ENTRIES",
    "MAX_SUPERSEDES",
    "MAX_TRAVERSAL_DEPTH",
    "MAX_LINEAGE_DEPTH",
    "MAX_PATH_RESULTS",
    "Metadata",
    "MetadataItem",
    "EMPTY_METADATA",
    # core models
    "EvidenceRef",
    "TemporalValidity",
    "MAX_SEARCH_QUERY_BYTES",
    "MAX_SEARCH_QUERY_SCALARS",
    "SEARCH_NORMALIZER_VERSION",
    "normalize_search_text",
    "TemporalFact",
    "TemporalHistory",
    "MemoryNode",
    "MemoryEdge",
    "MemoryGraph",
    "EMPTY_GRAPH",
    "node_id_for",
    "edge_id_for",
    "evidence_id_for",
    "revision_id_for",
    # resolution
    "EntityMention",
    "ResolutionConfig",
    "ResolvedEntity",
    "ResolutionResult",
    "EntityResolver",
    "Resolver",
    "normalize_label",
    # confidence
    "ConfidenceEngine",
    "ConfidencePolicy",
    "ConfidenceAssessment",
    # builder
    "MemoryGraphBuilder",
    "NodeInput",
    "EdgeInput",
    "BuildResult",
    # temporal traversal
    "subgraph_as_of",
    "active_edges_at",
    "neighbors_at",
    "attribute_at",
    "node_exists_at",
    # lineage
    "DecisionLineage",
    "LineageTrace",
    "LineageNode",
    "LineageEdgeRef",
    "LineagePath",
    # query
    "MemoryQueryEngine",
    "RelatedNode",
    "PathResult",
    # versioning
    "GraphRevision",
    "GraphHistory",
    "GraphDiff",
    "diff_graphs",
    "EMPTY_HISTORY",
    # projection / semantic bridge
    "to_semantic_graph",
    "to_semantic_node",
    "to_semantic_relationship",
    "MemoryGraphExecutor",
    "__version__",
]
