"""Store composition and resilient PostgreSQL lifecycle for the audit service.

The PostgreSQL backend owns one bounded ``psycopg_pool.ConnectionPool`` and
acquires a connection for each store operation. The existing append-only store
implementations continue to own their advisory locks, transactions, hash-chain
assignment, and composite-key idempotency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from typing import Annotated, Any, Protocol, TypeVar, cast

from emg_audit_client import (
    AuditEvent,
    AuditEventStore,
    AuditQuery,
    CustodyEvent,
    CustodyEventStore,
    CustodyQuery,
    IntegrityResult,
    SubmittedAuditEvent,
    SubmittedCustodyEvent,
)
from emg_audit_pipeline import (
    InMemoryAuditEventStore,
    InMemoryCustodyEventStore,
    PostgresAuditEventStore,
    PostgresCustodyEventStore,
)
from fastapi import Depends
from psycopg import Connection, OperationalError
from psycopg.pq import TransactionStatus

from .authn import SettingsDep
from .config import Settings

T = TypeVar("T")


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


def _create_pool(
    *,
    conninfo: str,
    kwargs: dict[str, Any],
    min_size: int,
    max_size: int,
    timeout: float,
    open: bool,
) -> _ConnectionPool:  # pragma: no cover - import/construction seam
    from psycopg_pool import ConnectionPool

    return cast(
        _ConnectionPool,
        ConnectionPool(
            conninfo=conninfo,
            kwargs=kwargs,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            open=open,
        ),
    )


@dataclass(frozen=True)
class StoreHealth:
    backend: str
    available: bool
    detail: str


class _PooledOperations:
    """Acquire/reset/return connections and replace operational failures."""

    def __init__(self, pool: _ConnectionPool, settings: Settings) -> None:
        self._pool = pool
        self._acquisition_timeout = settings.postgres_pool_acquisition_timeout_seconds
        self._attempts = settings.postgres_reconnect_attempts

    def run(self, operation: Callable[[Connection[Any]], T]) -> T:
        last_error: OperationalError | None = None
        for attempt in range(self._attempts):
            connection = self._pool.getconn(timeout=self._acquisition_timeout)
            try:
                return operation(connection)
            except OperationalError as exc:
                # The operation is safe to repeat: appends are idempotent under
                # their authenticated composite key and reads have no effects.
                # Closing makes psycopg_pool discard and replace this connection.
                connection.close()
                last_error = exc
                if attempt + 1 == self._attempts:
                    raise
            finally:
                self._reset_before_return(connection)
                self._pool.putconn(connection)
        assert last_error is not None  # pragma: no cover - loop always returns/raises
        raise last_error

    @staticmethod
    def _reset_before_return(connection: Connection[Any]) -> None:
        if connection.closed:
            return
        try:
            if connection.info.transaction_status is not TransactionStatus.IDLE:
                connection.rollback()
        except Exception:
            # A connection that cannot be reset must not be reused. A closed
            # connection returned to psycopg_pool is discarded and replaced.
            connection.close()


class PooledAuditEventStore:
    """AuditEventStore adapter that preserves the existing store semantics."""

    def __init__(self, operations: _PooledOperations) -> None:
        self._operations = operations

    def append(
        self,
        event: SubmittedAuditEvent,
        *,
        source_principal: str,
        tenant_id: str | None = None,
    ) -> AuditEvent:
        return self._operations.run(
            lambda connection: PostgresAuditEventStore(connection).append(
                event,
                source_principal=source_principal,
                tenant_id=tenant_id,
            )
        )

    def query(self, query: AuditQuery) -> list[AuditEvent]:
        return self._operations.run(
            lambda connection: PostgresAuditEventStore(connection).query(query)
        )

    def verify_integrity(self) -> IntegrityResult:
        return self._operations.run(
            lambda connection: PostgresAuditEventStore(connection).verify_integrity()
        )


class PooledCustodyEventStore:
    """CustodyEventStore adapter sharing the audit service connection pool."""

    def __init__(self, operations: _PooledOperations) -> None:
        self._operations = operations

    def append(self, event: SubmittedCustodyEvent, *, source_principal: str) -> CustodyEvent:
        return self._operations.run(
            lambda connection: PostgresCustodyEventStore(connection).append(
                event, source_principal=source_principal
            )
        )

    def query(self, query: CustodyQuery) -> list[CustodyEvent]:
        return self._operations.run(
            lambda connection: PostgresCustodyEventStore(connection).query(query)
        )

    def verify_integrity(self) -> IntegrityResult:
        return self._operations.run(
            lambda connection: PostgresCustodyEventStore(connection).verify_integrity()
        )


class AuditStoreRuntime:
    """Own the one production pool and both append-only store adapters."""

    def __init__(self, settings: Settings, *, pool_factory: PoolFactory = _create_pool) -> None:
        statement_ms = max(1, round(settings.postgres_statement_timeout_seconds * 1000))
        lock_ms = max(1, round(settings.postgres_lock_timeout_seconds * 1000))
        self._pool = pool_factory(
            conninfo=settings.postgres_dsn,
            kwargs={
                "connect_timeout": max(1, ceil(settings.postgres_connect_timeout_seconds)),
                "options": f"-c statement_timeout={statement_ms} -c lock_timeout={lock_ms}",
            },
            min_size=settings.postgres_pool_min_size,
            max_size=settings.postgres_pool_max_size,
            timeout=settings.postgres_pool_acquisition_timeout_seconds,
            open=False,
        )
        self._connect_timeout = settings.postgres_connect_timeout_seconds
        self._shutdown_timeout = settings.postgres_shutdown_timeout_seconds
        operations = _PooledOperations(self._pool, settings)
        self.audit_store: AuditEventStore = PooledAuditEventStore(operations)
        self.custody_store: CustodyEventStore = PooledCustodyEventStore(operations)
        self._opened = False
        self._closed = False
        self._lock = Lock()

    def open(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("audit PostgreSQL connection pool is closed")
            if self._opened:
                return
            self._pool.open(wait=True, timeout=self._connect_timeout)
            self._opened = True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._pool.close(timeout=self._shutdown_timeout)


@dataclass(frozen=True)
class _MemoryRuntime:
    audit_store: AuditEventStore
    custody_store: CustodyEventStore

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None


RuntimeKey = tuple[str, str, float, float, float, float, int, int, int, float]
_runtime_lock = Lock()
_active_runtimes: dict[RuntimeKey, AuditStoreRuntime | _MemoryRuntime] = {}


def _runtime_key(settings: Settings) -> RuntimeKey:
    return (
        settings.store_backend,
        settings.postgres_dsn,
        settings.postgres_connect_timeout_seconds,
        settings.postgres_pool_acquisition_timeout_seconds,
        settings.postgres_statement_timeout_seconds,
        settings.postgres_lock_timeout_seconds,
        settings.postgres_pool_min_size,
        settings.postgres_pool_max_size,
        settings.postgres_reconnect_attempts,
        settings.postgres_shutdown_timeout_seconds,
    )


def _runtime_for(settings: Settings) -> AuditStoreRuntime | _MemoryRuntime:
    key = _runtime_key(settings)
    with _runtime_lock:
        runtime = _active_runtimes.get(key)
        if runtime is None:
            if settings.store_backend == "postgres":
                runtime = AuditStoreRuntime(settings)
            else:
                runtime = _MemoryRuntime(
                    audit_store=InMemoryAuditEventStore(),
                    custody_store=InMemoryCustodyEventStore(),
                )
            _active_runtimes[key] = runtime
        return runtime


def open_store_runtime(settings: Settings) -> None:
    """Construct and synchronously verify the configured production pool."""

    _runtime_for(settings).open()


def close_store_runtime() -> None:
    """Close every constructed pool and clear process-local runtime state."""

    with _runtime_lock:
        runtimes = tuple(_active_runtimes.values())
        _active_runtimes.clear()
    first_error: Exception | None = None
    for runtime in runtimes:
        try:
            runtime.close()
        except Exception as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def store_dependency(settings: SettingsDep) -> AuditEventStore:
    return _runtime_for(settings).audit_store


StoreDep = Annotated[AuditEventStore, Depends(store_dependency)]


def custody_store_dependency(settings: SettingsDep) -> CustodyEventStore:
    return _runtime_for(settings).custody_store


CustodyStoreDep = Annotated[CustodyEventStore, Depends(custody_store_dependency)]


def store_health(store: AuditEventStore, settings: Settings) -> StoreHealth:
    """Probe reachability without fabricating or mutating an audit record."""

    try:
        store.query(AuditQuery(limit=1))
        return StoreHealth(
            backend=settings.store_backend,
            available=True,
            detail="store reachable",
        )
    except Exception as exc:  # pragma: no cover - readiness tests use a fake
        return StoreHealth(
            backend=settings.store_backend,
            available=False,
            detail=f"store unavailable: {exc}",
        )
