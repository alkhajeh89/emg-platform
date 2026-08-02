"""PostgreSQL connection ownership seam (Phase 2, Sprint 4 Task 2A).

``ConnectionProvider`` separates connection acquisition/lifetime from repository
behavior. ``DirectConnectionProvider`` is the non-pooling implementation: every
acquisition opens one settings-backed connection and closes it deterministically
on context exit. ``PooledConnectionProvider`` lazily owns a bounded psycopg pool
behind the same protocol without changing repositories or transaction ownership.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from math import ceil
from threading import Lock
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from psycopg.pq import TransactionStatus

from ..config import PersistenceSettings

if TYPE_CHECKING:
    from psycopg import Connection

ConnectionFactory = Callable[[PersistenceSettings], "Connection[Any]"]


class _ConnectionPool(Protocol):
    def open(self, *, wait: bool = False, timeout: float = 30.0) -> None: ...

    def getconn(self, timeout: float | None = None) -> Connection[Any]: ...

    def putconn(self, connection: Connection[Any]) -> None: ...

    def close(self, timeout: float = 5.0) -> None: ...


class PoolFactory(Protocol):
    def __call__(
        self,
        *,
        conninfo: str,
        kwargs: dict[str, Any],
        min_size: int,
        max_size: int,
        timeout: float,
        open: bool,
    ) -> _ConnectionPool: ...


def _create_pool(  # pragma: no cover - thin import seam
    *,
    conninfo: str,
    kwargs: dict[str, Any],
    min_size: int,
    max_size: int,
    timeout: float,
    open: bool,
) -> _ConnectionPool:
    from psycopg_pool import ConnectionPool

    return ConnectionPool(
        conninfo=conninfo,
        kwargs=kwargs,
        min_size=min_size,
        max_size=max_size,
        timeout=timeout,
        open=open,
    )


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


class PooledConnectionProvider:
    """Lazily acquire bounded, reusable PostgreSQL connections.

    Provider construction performs no I/O and does not construct the underlying
    pool. The first acquisition creates and opens it, preserving the existing
    lazy runtime-composition behavior.
    """

    def __init__(
        self,
        settings: PersistenceSettings,
        *,
        pool_factory: PoolFactory = _create_pool,
    ) -> None:
        if settings.postgres_dsn is None:
            raise ValueError("postgres_dsn is not configured")
        self._settings = settings
        self._postgres_dsn = settings.postgres_dsn
        self._pool_factory = pool_factory
        self._pool: _ConnectionPool | None = None
        self._lock = Lock()
        self._closed = False

    def _get_pool(self) -> _ConnectionPool:
        with self._lock:
            if self._closed:
                raise RuntimeError("PostgreSQL connection pool is closed")
            if self._pool is None:
                pool = self._pool_factory(
                    conninfo=self._postgres_dsn,
                    kwargs={
                        "connect_timeout": max(1, ceil(self._settings.connect_timeout_seconds)),
                    },
                    min_size=self._settings.postgres_pool_min_size,
                    max_size=self._settings.postgres_pool_max_size,
                    timeout=self._settings.connect_timeout_seconds,
                    open=False,
                )
                try:
                    pool.open(wait=False)
                except Exception:
                    pool.close()
                    raise
                self._pool = pool
            return self._pool

    @contextmanager
    def acquire(self) -> Iterator[Connection[Any]]:
        pool = self._get_pool()
        connection = pool.getconn(timeout=self._settings.connect_timeout_seconds)
        try:
            yield connection
        finally:
            self._reset_before_return(connection)
            pool.putconn(connection)

    @staticmethod
    def _reset_before_return(connection: Connection[Any]) -> None:
        try:
            if connection.info.transaction_status is not TransactionStatus.IDLE:
                connection.rollback()
        except Exception:
            # A connection that cannot be reset must never be reused. The pool
            # discards closed connections and replaces them within its bounds.
            with suppress(Exception):
                connection.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pool = self._pool
            self._pool = None
        if pool is not None:
            pool.close()
