"""Standard error subclasses shared by every service.

This is a minimal, cross-cutting catalog. Domain-specific errors (e.g. an
Investigation Agent scope violation) belong to their owning service and
should subclass one of these rather than EMGError directly.
"""

from __future__ import annotations

from .base import EMGError


class ValidationError(EMGError):
    error_code = "VALIDATION_ERROR"


class AuthorizationError(EMGError):
    """Raised when a caller cannot be authenticated, or an authenticated
    caller's identity cannot be established (e.g. an invalid/expired token,
    or a token missing a required claim). This is the platform's existing
    401 (authentication-failure) error — every current raise site
    (`services/audit`, `services/identity`, `services/knowledge-graph`)
    maps it to HTTP 401. It is distinct from :class:`PermissionDeniedError`
    (403): an authenticated caller who is simply not permitted to perform
    an action is a *different* failure, not an authentication failure, and
    must not be raised as this error (ADR-025 §8.6 — reusing this error for
    both meanings would make every existing 401 call site ambiguous about
    which failure occurred). Every raise site must be paired with an audit
    event once the audit pipeline lands (FEAT-04-1) — see Engineering
    Backlog v1.0, US-03 acceptance criteria."""

    error_code = "AUTHORIZATION_ERROR"


class PermissionDeniedError(EMGError):
    """Raised when an authenticated, identity-resolved caller is denied by
    an authorization (Policy Enforcement Point) decision — i.e. a
    :class:`emg_auth_client.Decision` with ``outcome == "deny"``.

    Introduced by ADR-025 (Knowledge Graph Tenant & Authorization Model),
    Group C1, as the platform-wide, shared error for this outcome — not a
    service-specific error — because no existing `emg_errors` type
    distinguished "authenticated but not permitted" from
    :class:`AuthorizationError`'s existing "not authenticated" meaning
    (ADR-025 §5, §8.6: a repository-wide grep found no prior 403 error type
    or route mapping anywhere). Every adopting service maps this to HTTP
    403 in its own error-status map; see
    `emg_knowledge_graph_api.errors.ERROR_STATUS_MAP` for the first adopter.
    """

    error_code = "PERMISSION_DENIED"


class NotFoundError(EMGError):
    error_code = "NOT_FOUND"


class ConflictError(EMGError):
    error_code = "CONFLICT"


class UpstreamServiceError(EMGError):
    """Raised when a downstream/upstream service call fails."""

    error_code = "UPSTREAM_SERVICE_ERROR"
