"""Explicit PostgreSQL transaction ownership (Phase 2, Sprint 4 Task 2B).

The boundary composes a :class:`ConnectionProvider` with psycopg's explicit
``connection.transaction()`` context. It owns transaction and connection
lifetime only; repositories remain responsible for SQL, while later Sprint 4
tasks own write-path decisions and orchestration.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .pool import ConnectionProvider

if TYPE_CHECKING:
    from psycopg import Connection


@runtime_checkable
class TransactionProvider(Protocol):
    """Internal provider of one explicit PostgreSQL transaction scope."""

    def transaction(self) -> AbstractContextManager[Connection[Any]]:
        """Yield one connection inside one explicit transaction."""
        ...


class PostgresTransactionProvider:
    """Own explicit transaction scopes over provider-managed connections."""

    def __init__(self, connections: ConnectionProvider) -> None:
        self._connections = connections

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        with self._connections.acquire() as connection, connection.transaction():
            yield connection
