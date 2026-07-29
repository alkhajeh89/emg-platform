"""GraphStore / GraphRevisionReader wiring for the Knowledge Graph Query API.

Settings-driven backend selection, mirroring
`emg_audit_service.store`'s exact pattern: `memory` (tests / local without a
database) or `postgres` (`PostgresNeo4jGraphStore`, PostgreSQL-authoritative;
its optional Neo4j serving-projection parameter is left unset — this
sprint's STRICT RULES forbid touching Neo4j, and ADR-024 §19 does not
require it for the query engine). Persistence adapters are instantiated only
here, never inside a route handler.

Both backends satisfy `GraphStore` *and* `GraphRevisionReader` on the same
object (exactly as `InMemoryGraphStore`/`PostgresNeo4jGraphStore` already do
for the application-layer tests in `emg_knowledge_graph`), so one dependency
wires both `KnowledgeGraphApplication` constructor arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Protocol, runtime_checkable

from emg_knowledge_graph import (
    AtomicMutationExecutionPort,
    InMemoryAtomicMutationExecution,
)
from emg_platform_core import InMemoryGraphStore
from emg_platform_core.ports import GraphRevisionReader, GraphStore
from fastapi import Depends

from .authn import SettingsDep
from .config import Settings


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
        from emg_persistence.postgres.pool import DirectConnectionProvider
        from emg_persistence.postgres.transactions import ContextBoundTransactionProvider
        from emg_persistence.store import PostgresNeo4jGraphStore

        persistence_settings = PersistenceSettings(
            postgres_dsn=settings.postgres_dsn,
            connect_timeout_seconds=settings.postgres_connect_timeout_seconds,
        )
        connections = DirectConnectionProvider(persistence_settings)
        transactions = ContextBoundTransactionProvider(connections)
        return StoreRuntime(
            store=PostgresNeo4jGraphStore(transactions),
            atomic_mutations=PostgresAtomicMutationExecution(transactions),
        )
    return StoreRuntime(
        store=_memory_store_singleton(),
        atomic_mutations=_memory_atomic_mutations_singleton(),
    )


@lru_cache
def _runtime_singleton_for(backend: str, dsn: str) -> StoreRuntime:
    # Cache keyed by the config that determines the store, so the app reuses
    # one store/connection-provider per configuration (mirrors
    # emg_audit_service.store._store_singleton_for exactly).
    return _build_runtime(Settings(store_backend=backend, postgres_dsn=dsn))


def _store_singleton_for(backend: str, dsn: str) -> GraphStoreAndRevisionReader:
    return _runtime_singleton_for(backend, dsn).store


def graph_store_dependency(settings: SettingsDep) -> GraphStoreAndRevisionReader:
    return _store_singleton_for(settings.store_backend, settings.postgres_dsn)


GraphStoreDep = Annotated[GraphStoreAndRevisionReader, Depends(graph_store_dependency)]


def atomic_mutation_execution_dependency(settings: SettingsDep) -> AtomicMutationExecutionPort:
    return _runtime_singleton_for(settings.store_backend, settings.postgres_dsn).atomic_mutations


AtomicMutationExecutionDep = Annotated[
    AtomicMutationExecutionPort, Depends(atomic_mutation_execution_dependency)
]


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
