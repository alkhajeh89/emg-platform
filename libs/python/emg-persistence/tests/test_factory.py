"""build_graph_store: backend selection and lazy dependency injection."""

from __future__ import annotations

import neo4j
import psycopg
import pytest
from emg_persistence import (
    PersistenceSettings,
    PostgresNeo4jGraphStore,
    build_graph_store,
)
from emg_persistence.neo4j.lazy import LazyNeo4jProjection
from emg_persistence.postgres import (
    PooledConnectionProvider,
    PostgresRevisionRepository,
    PostgresTransactionProvider,
)
from emg_platform_core import GraphStore, InMemoryGraphStore


def test_default_returns_in_memory_graphstore() -> None:
    store = build_graph_store()
    assert isinstance(store, InMemoryGraphStore)
    assert isinstance(store, GraphStore)  # satisfies the unchanged Phase 1 port


def test_explicit_unconfigured_settings_return_in_memory() -> None:
    store = build_graph_store(PersistenceSettings())
    assert isinstance(store, InMemoryGraphStore)


def test_postgres_configuration_returns_persistent_graphstore() -> None:
    settings = PersistenceSettings(postgres_dsn="postgresql://u@h/db")
    store = build_graph_store(settings)

    assert isinstance(store, PostgresNeo4jGraphStore)
    assert isinstance(store, GraphStore)
    assert store._projection is None


def test_neo4j_only_still_in_memory() -> None:
    # Neo4j is projection-only (ADR-1); without postgres_dsn persistence is not
    # considered configured, so the in-memory store is returned.
    store = build_graph_store(PersistenceSettings(neo4j_uri="neo4j://h"))
    assert isinstance(store, InMemoryGraphStore)


def test_factory_returns_fresh_instances() -> None:
    assert build_graph_store() is not build_graph_store()


def test_postgres_and_neo4j_configuration_does_not_construct_neo4j(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neo4j_calls = 0

    def forbidden_driver(*args: object, **kwargs: object) -> None:
        nonlocal neo4j_calls
        neo4j_calls += 1
        raise AssertionError("Neo4j must remain lazy during factory construction")

    monkeypatch.setattr(neo4j.GraphDatabase, "driver", forbidden_driver)
    settings = PersistenceSettings(
        postgres_dsn="postgresql://u@h/db",
        neo4j_uri="neo4j://h",
    )

    store = build_graph_store(settings)

    assert isinstance(store, PostgresNeo4jGraphStore)
    assert isinstance(store._projection, LazyNeo4jProjection)
    assert store._projection._settings is settings
    assert neo4j_calls == 0


def test_construction_does_not_eagerly_acquire_postgres_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect_calls = 0

    def forbidden_connect(*args: object, **kwargs: object) -> None:
        nonlocal connect_calls
        connect_calls += 1
        raise AssertionError("PostgreSQL must not connect during factory construction")

    monkeypatch.setattr(psycopg, "connect", forbidden_connect)

    store = build_graph_store(PersistenceSettings(postgres_dsn="postgresql://u@h/db"))

    assert isinstance(store, PostgresNeo4jGraphStore)
    assert connect_calls == 0


def test_dependencies_are_wired_from_the_exact_settings_instance() -> None:
    settings = PersistenceSettings(
        postgres_dsn="postgresql://u@h/db",
        connect_timeout_seconds=3.5,
    )

    store = build_graph_store(settings)

    assert isinstance(store, PostgresNeo4jGraphStore)
    transactions = store._transactions
    assert isinstance(transactions, PostgresTransactionProvider)
    connections = transactions._connections
    assert isinstance(connections, PooledConnectionProvider)
    assert connections._settings is settings
    assert store._repository_factory is PostgresRevisionRepository
