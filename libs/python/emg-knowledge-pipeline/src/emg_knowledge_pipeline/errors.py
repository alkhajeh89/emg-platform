"""Typed ingestion errors + machine-readable problem records (FEAT-05-2).

Errors derive from `emg_errors.EMGError` so they map cleanly to the platform's
error envelope and structured logs, and each carries a stable machine-readable
`error_code`. Validation failures aggregate the underlying reasons (ontology
conformance errors, bound violations, cycles) into a tuple of typed
`IngestionProblem` records, so a caller gets one typed error with a full,
machine-readable breakdown — never a bare exception or a partial result.
"""

from __future__ import annotations

from emg_errors import ConflictError, EMGError, ValidationError
from pydantic import BaseModel, ConfigDict

# --- machine-readable problem codes ----------------------------------------

CODE_BATCH_TOO_LARGE = "INGESTION_BATCH_TOO_LARGE"
CODE_FIELD_TOO_LONG = "INGESTION_FIELD_TOO_LONG"
CODE_METADATA_TOO_LARGE = "INGESTION_METADATA_TOO_LARGE"
CODE_SENSITIVE_METADATA_KEY = "INGESTION_SENSITIVE_METADATA_KEY"
CODE_UNKNOWN_ENTITY_TYPE = "INGESTION_UNKNOWN_ENTITY_TYPE"
CODE_ONTOLOGY_NONCONFORMANT = "INGESTION_ONTOLOGY_NONCONFORMANT"
CODE_DUPLICATE_ENTITY_IN_BATCH = "INGESTION_DUPLICATE_ENTITY_IN_BATCH"
CODE_DUPLICATE_RELATIONSHIP_IN_BATCH = "INGESTION_DUPLICATE_RELATIONSHIP_IN_BATCH"
CODE_DANGLING_ENDPOINT = "INGESTION_DANGLING_ENDPOINT"
CODE_RELATIONSHIP_NONCONFORMANT = "INGESTION_RELATIONSHIP_NONCONFORMANT"
CODE_CYCLIC_DEPENDENCY = "INGESTION_CYCLIC_DEPENDENCY"
CODE_INVALID_EFFECTIVE_DATES = "INGESTION_INVALID_EFFECTIVE_DATES"


class IngestionProblem(BaseModel):
    """One typed, machine-readable ingestion failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    location: str | None = None


class IngestionError(EMGError):
    """Base class for all ingestion-pipeline errors."""

    error_code = "INGESTION_ERROR"


class IngestionValidationError(ValidationError):
    """Raised when an ingestion request fails validation (ontology
    non-conformance, bound violation, duplicate, cycle, ...). Carries a tuple of
    typed `IngestionProblem` records for machine consumption; nothing is
    persisted."""

    def __init__(self, problems: tuple[IngestionProblem, ...]) -> None:
        code = problems[0].code if problems else "INGESTION_VALIDATION_ERROR"
        message = "; ".join(f"{p.code}: {p.message}" for p in problems) or "ingestion invalid"
        super().__init__(message, error_code=code)
        self.problems = problems


class IngestionConflictError(ConflictError):
    """Raised when an ingestion would violate an integrity constraint that is not
    a clean idempotent no-op (e.g. the same id resolved to a conflicting
    record)."""

    error_code = "INGESTION_CONFLICT"


class GraphPersistenceError(IngestionError):
    """Raised when the graph store fails to persist a transaction. The pipeline
    rolls the transaction back before surfacing this, so no partial graph is
    left behind."""

    error_code = "GRAPH_PERSISTENCE_ERROR"
