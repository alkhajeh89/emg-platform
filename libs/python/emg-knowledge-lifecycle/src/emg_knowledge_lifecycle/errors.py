"""Lifecycle error types (FEAT-05-5).

Cross-model semantic rejections (an illegal state transition, a cyclic or
orphaned chain, a duplicate active version) surface as typed errors derived from
the platform-wide `emg_errors.EMGError` hierarchy, so lifecycle rejection is
handled and logged the same way as every other EMG error. Field- and
structure-level rejections raised inside pydantic validators surface as
`pydantic.ValidationError`.
"""

from __future__ import annotations

from emg_errors import ValidationError


class LifecycleError(ValidationError):
    """Base for lifecycle-semantic rejections. Subclasses `ValidationError` so a
    caller can catch it generically alongside other validation failures."""

    error_code = "LIFECYCLE_ERROR"


class InvalidTransitionError(LifecycleError):
    """Raised when a state transition is not permitted by the lifecycle state
    machine."""

    error_code = "LIFECYCLE_INVALID_TRANSITION"


class InvalidChainError(LifecycleError):
    """Raised when a version chain is structurally invalid (cycle, orphan,
    duplicate active version, mixed entities, unresolved parent, etc.)."""

    error_code = "LIFECYCLE_INVALID_CHAIN"


class MissingReasonError(LifecycleError):
    """Raised when a `LifecyclePolicy` requires a reason for a transition but the
    `LifecycleEvent` carries none. (A whitespace-only reason is already rejected
    at event construction by the safe-text validator.)"""

    error_code = "LIFECYCLE_REASON_REQUIRED"
