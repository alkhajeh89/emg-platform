"""GraphStore / GraphRevisionReader wiring for the Knowledge Graph Query API.

Settings-driven backend selection, mirroring
`emg_audit_service.store`'s exact pattern: `memory` (tests / local without a
database) or `postgres` (`PostgresNeo4jGraphStore`, PostgreSQL-authoritative,
with an optional lazy Neo4j serving projection). Persistence adapters are
instantiated only here, never inside a route handler.

Both backends satisfy `GraphStore` *and* `GraphRevisionReader` on the same
object (exactly as `InMemoryGraphStore`/`PostgresNeo4jGraphStore` already do
for the application-layer tests in `emg_knowledge_graph`), so one dependency
wires both `KnowledgeGraphApplication` constructor arguments.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from threading import Lock
from typing import Annotated, Protocol, TypeAlias, runtime_checkable

from emg_knowledge_graph import (
    AtomicMutationExecutionPort,
    InMemoryAtomicMutationExecution,
)
from emg_platform_core import InMemoryGraphStore
from emg_platform_core.ports import GraphRevisionReader, GraphStore
from fastapi import Depends
from pydantic import SecretStr

from .authn import SettingsDep
from .config import Settings, StoreBackend

RuntimeKey: TypeAlias = tuple[
    StoreBackend,
    str,
    float,
    int,
    int,
    str | None,
    str | None,
    SecretStr | None,
    int,
    int,
    int,
    int,
]


@runtime_checkable
class GraphStoreAndRevisionReader(GraphStore, GraphRevisionReader, Protocol):
    """The combined capability every backend below provides — one object
    usable as both `KnowledgeGraphApplication` constructor arguments."""


@dataclass(frozen=True)
class StoreHealth:
    """Mirrors `emg_audit_service.store.StoreHealth` exactly."""

    backend: str
    available: bool
    detail: str


@dataclass(frozen=True)
class StoreRuntime:
    """One store plus the atomic port sharing its transaction substrate."""

    store: GraphStoreAndRevisionReader
    atomic_mutations: AtomicMutationExecutionPort
    close_resources: tuple[Callable[[], None], ...]

    def close(self) -> None:
        first_error: Exception | None = None
        for close_resource in self.close_resources:
            try:
                close_resource()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


def _no_op_close() -> None:
    return None


_runtime_registry_lock = Lock()
_active_runtimes: dict[RuntimeKey, StoreRuntime] = {}


@lru_cache
def _memory_store_singleton() -> InMemoryGraphStore:
    return InMemoryGraphStore()


@lru_cache
def _memory_atomic_mutations_singleton() -> InMemoryAtomicMutationExecution:
    return InMemoryAtomicMutationExecution()


def _build_runtime(settings: Settings) -> StoreRuntime:
    if settings.store_backend == "postgres":
        # Imported lazily so `psycopg`/`emg_persistence` are only required
        # when the postgres backend is actually selected (mirrors
        # emg_audit_service.store's lazy `import psycopg`).
        from emg_knowledge_graph_infrastructure import PostgresAtomicMutationExecution
        from emg_persistence.config import PersistenceSettings
        from emg_persistence.neo4j.lazy import LazyNeo4jProjection
        from emg_persistence.postgres.pool import PooledConnectionProvider
        from emg_persistence.postgres.transactions import ContextBoundTransactionProvider
        from emg_persistence.store import PostgresNeo4jGraphStore

        persistence_settings = PersistenceSettings(
            postgres_dsn=settings.postgres_dsn,
            connect_timeout_seconds=settings.postgres_connect_timeout_seconds,
            postgres_pool_min_size=settings.postgres_pool_min_size,
            postgres_pool_max_size=settings.postgres_pool_max_size,
            neo4j_uri=settings.neo4j_uri,
            neo4j_user=settings.neo4j_user,
            neo4j_password=settings.neo4j_password,
            neo4j_max_pool_size=settings.neo4j_max_pool_size,
        )
        connections = PooledConnectionProvider(persistence_settings)
        projection = (
            LazyNeo4jProjection(persistence_settings)
            if persistence_settings.neo4j_uri is not None
            else None
        )
        transactions = ContextBoundTransactionProvider(connections)
        return StoreRuntime(
            store=PostgresNeo4jGraphStore(
                transactions,
                projection=projection,
                search_representation_retention=timedelta(
                    seconds=settings.search_representation_retention_seconds
                ),
                search_cleanup_interval=timedelta(seconds=settings.search_cleanup_interval_seconds),
                search_cleanup_batch_size=settings.search_cleanup_batch_size,
            ),
            atomic_mutations=PostgresAtomicMutationExecution(transactions),
            close_resources=(
                (() if projection is None else (projection.close,)) + (connections.close,)
            ),
        )
    return StoreRuntime(
        store=_memory_store_singleton(),
        atomic_mutations=_memory_atomic_mutations_singleton(),
        close_resources=(_no_op_close,),
    )


def _runtime_singleton_for(
    backend: StoreBackend,
    dsn: str,
    connect_timeout_seconds: float,
    pool_min_size: int,
    pool_max_size: int,
    neo4j_uri: str | None,
    neo4j_user: str | None,
    neo4j_password: SecretStr | None,
    neo4j_max_pool_size: int,
    search_representation_retention_seconds: int = 3600,
    search_cleanup_interval_seconds: int = 900,
    search_cleanup_batch_size: int = 500,
) -> StoreRuntime:
    # Cache keyed by the config that determines the store, so the app reuses
    # one store/connection-provider per configuration.
    key: RuntimeKey = (
        backend,
        dsn,
        connect_timeout_seconds,
        pool_min_size,
        pool_max_size,
        neo4j_uri,
        neo4j_user,
        neo4j_password,
        neo4j_max_pool_size,
        search_representation_retention_seconds,
        search_cleanup_interval_seconds,
        search_cleanup_batch_size,
    )
    with _runtime_registry_lock:
        runtime = _active_runtimes.get(key)
        if runtime is None:
            # Pool construction is lazy, so holding the lock here performs no
            # datastore I/O and prevents duplicate pools under concurrent first use.
            runtime = _build_runtime(
                Settings(
                    store_backend=backend,
                    postgres_dsn=dsn,
                    postgres_connect_timeout_seconds=connect_timeout_seconds,
                    postgres_pool_min_size=pool_min_size,
                    postgres_pool_max_size=pool_max_size,
                    neo4j_uri=neo4j_uri,
                    neo4j_user=neo4j_user,
                    neo4j_password=neo4j_password,
                    neo4j_max_pool_size=neo4j_max_pool_size,
                    search_representation_retention_seconds=(
                        search_representation_retention_seconds
                    ),
                    search_cleanup_interval_seconds=search_cleanup_interval_seconds,
                    search_cleanup_batch_size=search_cleanup_batch_size,
                )
            )
            _active_runtimes[key] = runtime
        return runtime


def _store_singleton_for(
    backend: StoreBackend,
    dsn: str,
    connect_timeout_seconds: float,
    pool_min_size: int,
    pool_max_size: int,
    neo4j_uri: str | None,
    neo4j_user: str | None,
    neo4j_password: SecretStr | None,
    neo4j_max_pool_size: int,
    search_representation_retention_seconds: int = 3600,
    search_cleanup_interval_seconds: int = 900,
    search_cleanup_batch_size: int = 500,
) -> GraphStoreAndRevisionReader:
    return _runtime_singleton_for(
        backend,
        dsn,
        connect_timeout_seconds,
        pool_min_size,
        pool_max_size,
        neo4j_uri,
        neo4j_user,
        neo4j_password,
        neo4j_max_pool_size,
        search_representation_retention_seconds,
        search_cleanup_interval_seconds,
        search_cleanup_batch_size,
    ).store


def graph_store_dependency(settings: SettingsDep) -> GraphStoreAndRevisionReader:
    return _store_singleton_for(
        settings.store_backend,
        settings.postgres_dsn,
        settings.postgres_connect_timeout_seconds,
        settings.postgres_pool_min_size,
        settings.postgres_pool_max_size,
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_max_pool_size,
        settings.search_representation_retention_seconds,
        settings.search_cleanup_interval_seconds,
        settings.search_cleanup_batch_size,
    )


GraphStoreDep = Annotated[GraphStoreAndRevisionReader, Depends(graph_store_dependency)]


def atomic_mutation_execution_dependency(settings: SettingsDep) -> AtomicMutationExecutionPort:
    return _runtime_singleton_for(
        settings.store_backend,
        settings.postgres_dsn,
        settings.postgres_connect_timeout_seconds,
        settings.postgres_pool_min_size,
        settings.postgres_pool_max_size,
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_max_pool_size,
        settings.search_representation_retention_seconds,
        settings.search_cleanup_interval_seconds,
        settings.search_cleanup_batch_size,
    ).atomic_mutations


AtomicMutationExecutionDep = Annotated[
    AtomicMutationExecutionPort, Depends(atomic_mutation_execution_dependency)
]


def close_store_runtime() -> None:
    """Close every constructed runtime pool and clear the process-local cache."""

    with _runtime_registry_lock:
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


def store_health(store: GraphStoreAndRevisionReader, settings: Settings) -> StoreHealth:
    """Probe the store for readiness reporting, mirroring
    `emg_audit_service.store.store_health` exactly: a cheap read that proves
    reachability without mutating anything or scanning a specific tenant's
    full graph. `GraphStore.tenants()` requires no tenant/principal argument,
    so it is well-suited to an unauthenticated `/readyz` probe — for the
    `postgres` backend this is a genuine round trip to the database; for the
    in-memory backend it is always available."""
    backend = settings.store_backend
    try:
        store.tenants()
        return StoreHealth(backend=backend, available=True, detail="store reachable")
    except Exception as exc:  # pragma: no cover - exercised via readiness tests with a fake
        return StoreHealth(backend=backend, available=False, detail=f"store unavailable: {exc}")
