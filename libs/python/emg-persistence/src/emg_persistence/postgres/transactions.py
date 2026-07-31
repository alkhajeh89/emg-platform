"""Explicit PostgreSQL transaction ownership (Phase 2, Sprint 4 Task 2B).

The boundary composes a :class:`ConnectionProvider` with psycopg's explicit
``connection.transaction()`` context. It owns transaction and connection
lifetime only; repositories remain responsible for SQL, while later Sprint 4
tasks own write-path decisions and orchestration.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _BoundConnection:
    connection: Connection[Any]
    owner: tuple[int, int | None]


def _execution_owner() -> tuple[int, int | None]:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), None if task is None else id(task)


class ContextBoundTransactionProvider:
    """Let existing repositories join one explicitly owned outer transaction.

    ``GraphStore`` continues to call the unchanged ``transaction()`` method.
    During ``outer_transaction()``, that call receives the already-bound
    connection and psycopg creates a savepoint rather than a separate commit.
    Context ownership prevents inherited async contexts from sharing a
    connection concurrently.
    """

    def __init__(self, connections: ConnectionProvider) -> None:
        self._connections = connections
        self._bound: ContextVar[_BoundConnection | None] = ContextVar(
            f"emg_atomic_connection_{id(self)}", default=None
        )

    def _current(self) -> Connection[Any] | None:
        bound = self._bound.get()
        if bound is None:
            return None
        if bound.owner != _execution_owner():
            raise RuntimeError("bound PostgreSQL transaction crossed an execution boundary")
        return bound.connection

    @contextmanager
    def outer_transaction(self) -> Iterator[Connection[Any]]:
        if self._bound.get() is not None:
            raise RuntimeError("an outer PostgreSQL transaction is already active")
        with self._connections.acquire() as connection, connection.transaction():
            token = self._bound.set(
                _BoundConnection(connection=connection, owner=_execution_owner())
            )
            try:
                yield connection
            finally:
                self._bound.reset(token)

    @contextmanager
    def transaction(self) -> Iterator[Connection[Any]]:
        connection = self._current()
        if connection is None:
            with self._connections.acquire() as acquired, acquired.transaction():
                yield acquired
            return
        with connection.transaction():
            yield connection
