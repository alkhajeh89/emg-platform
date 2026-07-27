"""Centralized application-error -> HTTP-response translation (Sprint 7.4).

Mirrors `emg_audit_service.main`'s `_ERROR_STATUS_MAP` + single
`EMGError` exception-handler pattern exactly: one dict from exception type to
status code, one handler registered against the shared `EMGError` base so
every current and future `emg_knowledge_graph` error is covered without a
per-error handler, and the same `emg_api_contracts.ApiResponse`/`ApiError`
JSON envelope every other service's error responses already use. No stack
trace or persistence detail is ever included — only `error_code` (stable,
machine-readable) and `message` (the exception's own human-readable text,
which every `emg_knowledge_graph` error constructs without embedding
persistence/adapter internals — see ADR-024 §17).
"""

from __future__ import annotations

from emg_errors import AuthorizationError, EMGError, PermissionDeniedError
from emg_knowledge_graph import (
    EdgeNotFoundError,
    EntityNotFoundError,
    InvalidQueryError,
    InvalidTemporalFilterError,
    PathDepthExceededError,
    QueryLimitExceededError,
    RevisionNotFoundError,
    UnsupportedHistoryCapabilityError,
)

# Order matters only for readability; lookup is by exact exception type via
# `type(exc)`, mirroring emg_audit_service.main's `_ERROR_STATUS_MAP`.
ERROR_STATUS_MAP: dict[type[EMGError], int] = {
    # Authentication/tenant-context failures (authn.py).
    AuthorizationError: 401,
    # Authorization (Policy Enforcement Point) denials — ADR-025 Group C7.
    # Deliberately a distinct status/error type from AuthorizationError
    # above: 401 means "who are you" failed, 403 means "you are known, but
    # not permitted to do this" (ADR-025 §8.6). No other existing error
    # mapping in this map changes.
    PermissionDeniedError: 403,
    # Knowledge Graph Query Engine application errors (ADR-024 §17).
    EntityNotFoundError: 404,
    EdgeNotFoundError: 404,
    RevisionNotFoundError: 404,
    InvalidQueryError: 422,
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
