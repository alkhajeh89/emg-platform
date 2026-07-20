"""PostgreSQL connection ownership seam (Phase 2, Sprint 4 Task 2A).

``ConnectionProvider`` separates connection acquisition/lifetime from repository
behavior. ``DirectConnectionProvider`` is the non-pooling implementation: every
acquisition opens one settings-backed connection and closes it deterministically
on context exit. A later pooling implementation can satisfy the same internal
protocol without changing repositories or the GraphStore assembly boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..config import PersistenceSettings

if TYPE_CHECKING:
    from psycopg import Connection

ConnectionFactory = Callable[[PersistenceSettings], "Connection[Any]"]


def connect(settings: PersistenceSettings) -> Connection[Any]:  # pragma: no cover - live DB
    """Open a psycopg connection to the configured PostgreSQL DSN.

    Raises:
        ValueError: if ``settings.postgres_dsn`` is not configured.
    """
    if settings.postgres_dsn is None:
        raise ValueError("postgres_dsn is not configured")
    import psycopg

    return psycopg.connect(
        settings.postgres_dsn,
        connect_timeout=int(settings.connect_timeout_seconds),
    )


@runtime_checkable
class ConnectionProvider(Protocol):
    """Internal owner of deterministic PostgreSQL connection lifetimes."""

    def acquire(self) -> AbstractContextManager[Connection[Any]]:
        """Acquire one connection and release it when the context exits."""
        ...


class DirectConnectionProvider:
    """Open and close one PostgreSQL connection per acquisition.

    This implementation deliberately performs no pooling and owns no transaction
    policy. Callers decide whether and when to enter ``connection.transaction()``.
    """

    def __init__(
        self,
        settings: PersistenceSettings,
        *,
        connection_factory: ConnectionFactory = connect,
    ) -> None:
        self._settings = settings
        self._connection_factory = connection_factory

    @contextmanager
    def acquire(self) -> Iterator[Connection[Any]]:
        connection = self._connection_factory(self._settings)
        try:
            yield connection
        finally:
            connection.close()
