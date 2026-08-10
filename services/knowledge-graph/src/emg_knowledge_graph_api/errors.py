"""Centralized application-error -> HTTP-response translation.

The shared ``EMGError`` handler uses this module's type map plus the
``SchemaNegotiationError`` failure discriminator required by ADR-033. The
response keeps the repository-standard ``ApiResponse``/``ApiError`` envelope.
No stack trace or persistence detail is included.
"""

from __future__ import annotations

from emg_errors import AuthorizationError, EMGError, PermissionDeniedError
from emg_knowledge_graph import (
    EdgeNotFoundError,
    EntityNotFoundError,
    IdempotencyContentionError,
    IdempotencyMismatchError,
    InvalidMutationCommandError,
    InvalidQueryError,
    InvalidSearchContinuationError,
    InvalidSearchRequestError,
    InvalidTemporalFilterError,
    LegacyIdempotencyConflictError,
    MutationAuthorizationConflictError,
    MutationBuildError,
    MutationReplayIntegrityError,
    MutationResourceMetadataError,
    PathDepthExceededError,
    QueryLimitExceededError,
    RevisionNotFoundError,
    SchemaNegotiationError,
    SearchUnavailableError,
    SearchWorkLimitError,
    UnsupportedFingerprintVersionError,
    UnsupportedHistoryCapabilityError,
)
from emg_persistence import PersistenceConflictError

# Order matters only for readability; non-schema lookup is by exact exception
# type via ``type(exc)``.
ERROR_STATUS_MAP: dict[type[EMGError], int] = {
    # Authentication/tenant-context failures (authn.py).
    AuthorizationError: 401,
    # Authorization (Policy Enforcement Point) denials — ADR-025 Group C7.
    # Deliberately a distinct status/error type from AuthorizationError
    # above: 401 means "who are you" failed, 403 means "you are known, but
    # not permitted to do this" (ADR-025 §8.6). No other existing error
    # mapping in this map changes.
    PermissionDeniedError: 403,
    # ADR-027/030 mutation failures.
    InvalidMutationCommandError: 400,
    MutationResourceMetadataError: 404,
    MutationAuthorizationConflictError: 409,
    IdempotencyMismatchError: 409,
    LegacyIdempotencyConflictError: 409,
    PersistenceConflictError: 409,
    MutationBuildError: 422,
    IdempotencyContentionError: 503,
    UnsupportedFingerprintVersionError: 503,
    MutationReplayIntegrityError: 500,
    # Knowledge Graph Query Engine application errors (ADR-024 §17).
    EntityNotFoundError: 404,
    EdgeNotFoundError: 404,
    RevisionNotFoundError: 404,
    InvalidQueryError: 422,
    InvalidSearchRequestError: 400,
    InvalidSearchContinuationError: 400,
    SearchWorkLimitError: 503,
    SearchUnavailableError: 503,
    QueryLimitExceededError: 422,
    PathDepthExceededError: 422,
    InvalidTemporalFilterError: 422,
    # No repository-wide "capability unavailable" status convention exists
    # yet (grepped: no other service maps any error to 501). 501 (Not
    # Implemented) is used literally, per its HTTP semantics: the server does
    # not support querying without a configured GraphRevisionReader in this
    # deployment. Flagged in the Sprint 7.4 final report as worth a small
    # repository-wide convention decision if a second service needs the same
    # "optional capability not configured" mapping.
    UnsupportedHistoryCapabilityError: 501,
}

DEFAULT_ERROR_STATUS = 500
_SCHEMA_CLIENT_FAILURES = frozenset(
    {
        "MALFORMED_SCHEMA",
        "UNKNOWN_SCHEMA",
        "RETIRED_SCHEMA",
        "INCOMPATIBLE_SCHEMA",
    }
)


def error_status(exc: EMGError) -> int:
    """Map one application/persistence error without changing its semantics."""

    if isinstance(exc, SchemaNegotiationError):
        return 422 if exc.failure_code in _SCHEMA_CLIENT_FAILURES else 500
    return ERROR_STATUS_MAP.get(type(exc), DEFAULT_ERROR_STATUS)


def error_headers(exc: EMGError) -> dict[str, str]:
    """Return transport-only retry metadata required by ADR-030."""

    if isinstance(exc, IdempotencyContentionError):
        return {"Retry-After": "1"}
    return {}


def public_error_message(exc: EMGError) -> str:
    """Return a stable client-safe message without exposing internal diagnostics."""

    status = error_status(exc)
    if isinstance(exc, AuthorizationError):
        return "Authentication failed"
    if isinstance(exc, PermissionDeniedError):
        return "Access denied"
    if status >= 500:
        return "Internal server error"
    return exc.message
