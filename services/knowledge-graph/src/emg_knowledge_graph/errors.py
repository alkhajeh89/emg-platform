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
