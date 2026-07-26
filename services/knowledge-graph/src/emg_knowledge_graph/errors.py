"""Application-level errors for knowledge-graph orchestration."""

from emg_errors import EMGError


class KnowledgeGraphApplicationError(EMGError):
    """Base error for failures owned by the application workflow."""

    error_code = "KNOWLEDGE_GRAPH_APPLICATION_ERROR"


class InvalidRevisionCommandError(KnowledgeGraphApplicationError):
    """The revision command violates an application-boundary invariant."""

    error_code = "KNOWLEDGE_GRAPH_INVALID_REVISION_COMMAND"


class RevisionBuildError(KnowledgeGraphApplicationError):
    """Validated ontology input could not be merged into the memory graph."""

    error_code = "KNOWLEDGE_GRAPH_REVISION_BUILD_FAILED"


class InvalidHistoryQueryError(KnowledgeGraphApplicationError):
    """A history query (list/get/compare) violates an application-boundary
    invariant — including invalid paging (ADR-023 §17). Raised before any
    ``GraphRevisionReader``/``GraphStore`` interaction."""

    error_code = "KNOWLEDGE_GRAPH_INVALID_HISTORY_QUERY"


class RevisionNotFoundError(KnowledgeGraphApplicationError):
    """No revision with the requested number exists for the tenant.

    Wraps the platform-core ``RevisionNotFoundError`` raised by a
    ``GraphRevisionReader`` implementation (ADR-023 §17). Raised identically
    whether the revision number is simply unused or belongs to a different
    tenant — the two cases must be indistinguishable to the caller."""

    error_code = "KNOWLEDGE_GRAPH_REVISION_NOT_FOUND"


class RevisionRestoreError(KnowledgeGraphApplicationError):
    """A historical revision could not be staged/committed during restore
    (ADR-023 §15, §17)."""

    error_code = "KNOWLEDGE_GRAPH_REVISION_RESTORE_FAILED"


class UnsupportedHistoryCapabilityError(KnowledgeGraphApplicationError):
    """A history method was called on a ``KnowledgeGraphApplication`` that was
    constructed without a ``GraphRevisionReader`` (ADR-023 §9, §17)."""

    error_code = "KNOWLEDGE_GRAPH_UNSUPPORTED_HISTORY_CAPABILITY"


# --- Query engine application errors (ADR-024 §17, Sprint 7.3 Phase 1) -------


class InvalidQueryError(KnowledgeGraphApplicationError):
    """A query command violates an application-boundary invariant — an
    invalid limit, an invalid cursor, an invalid revision number, or a
    malformed filter (ADR-024 §17). Raised before any
    ``GraphStore``/``GraphRevisionReader`` interaction."""

    error_code = "KNOWLEDGE_GRAPH_INVALID_QUERY"


class EntityNotFoundError(KnowledgeGraphApplicationError):
    """A requested ``node_id`` is absent from the selected tenant's resolved
    graph snapshot (ADR-024 §17). Raised identically whether the entity is
    simply unused or belongs to a different tenant's data."""

    error_code = "KNOWLEDGE_GRAPH_ENTITY_NOT_FOUND"


class EdgeNotFoundError(KnowledgeGraphApplicationError):
    """A requested ``edge_id`` is absent from the selected tenant's resolved
    graph snapshot (ADR-024 §17). Raised identically whether the edge is
    simply unused or belongs to a different tenant's data."""

    error_code = "KNOWLEDGE_GRAPH_EDGE_NOT_FOUND"


class QueryLimitExceededError(KnowledgeGraphApplicationError):
    """A requested hard safety limit — page size, neighbor-result count, or
    exact-property-predicate count — was exceeded (ADR-024 §17, §18). Raised
    before any store interaction."""

    error_code = "KNOWLEDGE_GRAPH_QUERY_LIMIT_EXCEEDED"


class InvalidTemporalFilterError(KnowledgeGraphApplicationError):
    """A ``valid_at`` value is invalid or timezone-naive (ADR-024 §13, §17).
    Raised before any store interaction."""

    error_code = "KNOWLEDGE_GRAPH_INVALID_TEMPORAL_FILTER"


class PathDepthExceededError(KnowledgeGraphApplicationError):
    """A requested path-search depth exceeds ``MAX_TRAVERSAL_DEPTH``
    (ADR-024 §15, §17). Raised before any graph snapshot is acquired."""

    error_code = "KNOWLEDGE_GRAPH_PATH_DEPTH_EXCEEDED"
