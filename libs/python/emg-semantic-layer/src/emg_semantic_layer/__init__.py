"""emg_semantic_layer — the storage-independent Semantic Layer (Module 7 —
Knowledge Graph Platform, EPIC-05, FEAT-05-4). Added Sprint 12.

Library-first, the same contract-first pattern as the other Module 7 libraries
(`emg-ontology`, `emg-trust-scoring`): this package defines a **deterministic,
immutable query/traversal/projection model** and a **single storage-binding
extension point**, decoupling every knowledge consumer (Search, GraphRAG, AI,
Decision, Presentation) from the underlying persistence technology (Architecture
Baseline §"Storage-technology independence"; Module 7 §10).

It defines *semantics only* — it **executes nothing**. Out of scope for Sprint 12
(deliberately): persistence, any database driver, Neo4j, networking, retrieval,
embeddings, AI, LLM integration, a REST API, UI, lifecycle management (FEAT-05-5),
and any wiring into the knowledge pipeline or trust-scoring runtime. Integration
happens only through the `SemanticQueryExecutor` extension point.

Security properties: query models are frozen and self-validating (malformed
queries are rejected at construction), traversal depth and page size are bounded
by construction, operators come from closed enums (no arbitrary code, no
injection surface), and the planner yields a deterministic, reproducible
execution model without executing.
"""

from .enums import (
    COLLECTION_OPERATORS,
    NULLARY_OPERATORS,
    BooleanOperator,
    FilterOperator,
    SortDirection,
    TraversalDirection,
)
from .errors import SemanticQueryError
from .execution import SemanticQueryExecutor
from .filters import ConditionValue, FilterCondition, SemanticFilter
from .graph import (
    PropertyValue,
    SemanticGraph,
    SemanticNode,
    SemanticRelationship,
)
from .limits import (
    DEFAULT_PAGE_LIMIT,
    MAX_FILTER_CONDITIONS,
    MAX_FILTER_DEPTH,
    MAX_FILTER_GROUPS,
    MAX_ORDERING_KEYS,
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    MAX_PROJECTION_FIELDS,
    MAX_RELATIONSHIP_TYPES_PER_STEP,
    MAX_SELECTOR_IDS,
    MAX_TRAVERSAL_DEPTH,
    MIN_PAGE_LIMIT,
)
from .planner import PlanStep, PlanStepKind, SemanticPlan, plan
from .query import (
    NodeSelector,
    Pagination,
    SemanticOrdering,
    SemanticProjection,
    SemanticQuery,
    SemanticTraversal,
    SortKey,
    TraversalStep,
)
from .result import PageInfo, SemanticResult
from .validation import ensure_safe_label

__version__ = "0.1.0"

__all__ = [
    # graph value objects
    "SemanticNode",
    "SemanticRelationship",
    "SemanticGraph",
    "PropertyValue",
    # enums
    "TraversalDirection",
    "FilterOperator",
    "BooleanOperator",
    "SortDirection",
    "NULLARY_OPERATORS",
    "COLLECTION_OPERATORS",
    # filters
    "FilterCondition",
    "SemanticFilter",
    "ConditionValue",
    # query model
    "NodeSelector",
    "TraversalStep",
    "SemanticTraversal",
    "SemanticProjection",
    "SortKey",
    "SemanticOrdering",
    "Pagination",
    "SemanticQuery",
    # planner (deterministic execution model)
    "plan",
    "SemanticPlan",
    "PlanStep",
    "PlanStepKind",
    # result model
    "SemanticResult",
    "PageInfo",
    # extension point
    "SemanticQueryExecutor",
    # errors
    "SemanticQueryError",
    # identifier/label validation helper
    "ensure_safe_label",
    # limits
    "MAX_TRAVERSAL_DEPTH",
    "MAX_FILTER_DEPTH",
    "MIN_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_OFFSET",
    "MAX_RELATIONSHIP_TYPES_PER_STEP",
    "MAX_SELECTOR_IDS",
    "MAX_FILTER_CONDITIONS",
    "MAX_FILTER_GROUPS",
    "MAX_PROJECTION_FIELDS",
    "MAX_ORDERING_KEYS",
    # version
    "__version__",
]
