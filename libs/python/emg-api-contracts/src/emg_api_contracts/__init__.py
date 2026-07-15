"""emg_api_contracts — REST/GraphQL response envelope and pagination
conventions shared across every service's API surface.

Scaffolded in Sprint 1 (FEAT-01-2 / Engineering Master Plan §2: "API client
conventions (Enterprise API Architecture)"). Defines shape only — no actual
API endpoints exist yet; Sprint 1 explicitly excludes API implementation.
"""

from .envelope import ApiError, ApiResponse
from .pagination import PaginatedResponse, PaginationParams

__version__ = "0.1.0"

__all__ = [
    "ApiResponse",
    "ApiError",
    "PaginationParams",
    "PaginatedResponse",
    "__version__",
]
