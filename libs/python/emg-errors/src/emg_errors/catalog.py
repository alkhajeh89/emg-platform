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
    """Raised on an authorization denial. Every raise site must be paired
    with an audit event once the audit pipeline lands (FEAT-04-1) — see
    Engineering Backlog v1.0, US-03 acceptance criteria."""

    error_code = "AUTHORIZATION_ERROR"


class NotFoundError(EMGError):
    error_code = "NOT_FOUND"


class ConflictError(EMGError):
    error_code = "CONFLICT"


class UpstreamServiceError(EMGError):
    """Raised when a downstream/upstream service call fails."""

    error_code = "UPSTREAM_SERVICE_ERROR"
