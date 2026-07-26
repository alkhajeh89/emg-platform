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
