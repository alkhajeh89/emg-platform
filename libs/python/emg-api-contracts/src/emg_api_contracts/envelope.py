"""Standard response/error envelope every REST and GraphQL surface uses,
per the Enterprise API Architecture. Kept dependency-light (stdlib
dataclasses) so both REST (FastAPI) and GraphQL resolvers can reuse it
without pulling in a web-framework dependency at the shared-library layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from emg_common_types import CorrelationId

T = TypeVar("T")


@dataclass(frozen=True)
class ApiError:
    error_code: str
    message: str


@dataclass(frozen=True)
class ApiResponse(Generic[T]):
    data: T | None
    error: ApiError | None
    correlation_id: CorrelationId | None = None
