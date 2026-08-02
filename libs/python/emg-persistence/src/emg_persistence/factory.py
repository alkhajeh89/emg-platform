"""Dependency-injection factory for the ``GraphStore``.

``build_graph_store`` is the single seam through which services obtain a
``GraphStore`` (the unchanged Phase 1 port). Selection is driven by
configuration, so callers depend on the *interface* and never construct a
concrete store directly.

Without an authoritative PostgreSQL DSN the deterministic Phase 1 in-memory
adapter remains the default. With PostgreSQL configured, the factory assembles
the Sprint 4 PostgreSQL-authoritative store without opening a connection or
constructing a Neo4j driver.
"""

from __future__ import annotations

from emg_platform_core import GraphStore, InMemoryGraphStore

from .config import PersistenceSettings
from .postgres import (
    PooledConnectionProvider,
    PostgresOutboxRepository,
    PostgresRevisionRepository,
    PostgresTransactionProvider,
)
from .store import PostgresNeo4jGraphStore


def _build_persistent_store(settings: PersistenceSettings) -> GraphStore:
    """Assemble the lazy, PostgreSQL-authoritative Sprint 4 store."""
    connections = PooledConnectionProvider(settings)
    transactions = PostgresTransactionProvider(connections)
    return PostgresNeo4jGraphStore(
        transactions,
        repository_factory=PostgresRevisionRepository,
        outbox_repository_factory=PostgresOutboxRepository,
    )


def build_graph_store(settings: PersistenceSettings | None = None) -> GraphStore:
    """Return a ``GraphStore`` selected from ``settings``.

    Args:
        settings: persistence configuration. If ``None``, a default
            ``PersistenceSettings()`` is used (in-memory mode unless the
            environment configures a datastore).

    Returns:
        The in-memory adapter without PostgreSQL, otherwise the lazy persistent
        PostgreSQL-authoritative adapter.
    """
    settings = settings if settings is not None else PersistenceSettings()
    if settings.is_persistence_configured:
        return _build_persistent_store(settings)
    return InMemoryGraphStore()
