"""emg_errors — base exception hierarchy shared across EMG services.

Scaffolded in Sprint 1 (FEAT-01-2: "error handling"). Every service raises
these (or subclasses) instead of ad hoc exceptions so error handling,
logging, and API error-envelope mapping (emg_api_contracts) stay consistent
platform-wide.
"""

from .base import EMGError
from .catalog import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UpstreamServiceError,
    ValidationError,
)

__version__ = "0.1.0"

__all__ = [
    "EMGError",
    "ValidationError",
    "AuthorizationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "UpstreamServiceError",
    "__version__",
]
