"""PostgreSQL pool composition and application-lifecycle coverage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import pytest
from emg_knowledge_graph_api import main, migrate, store
from emg_knowledge_graph_api.config import Settings
from emg_knowledge_graph_api.dependencies import (
    knowledge_graph_application_dependency,
    mutation_knowledge_graph_application_dependency,
)
from emg_persistence import PersistenceSettings
from emg_persistence.neo4j.lazy import LazyNeo4jProjection
from emg_persistence.postgres import PooledConnectionProvider
from fastapi.testclient import TestClient
from psycopg import Connection


def test_postgres_runtime_uses_lazy_pooled_provider() -> None:
    runtime = store._build_runtime(
        Settings(
            store_backend="postgres",
            postgres_dsn="postgresql://runtime@host/emg",
            postgres_connect_timeout_seconds=2.5,
            postgres_pool_min_size=2,
            postgres_pool_max_size=7,
            neo4j_uri="neo4j://projection-host",
            neo4j_user="neo4j",
            neo4j_password="projection-password",
            neo4j_max_pool_size=5,
        )
    )
    try:
        transactions = runtime.store._transactions
        connections = transactions._connections

        assert isinstance(connections, PooledConnectionProvider)
        assert connections._pool is None
        assert connections._settings == PersistenceSettings(
            postgres_dsn="postgresql://runtime@host/emg",
            connect_timeout_seconds=2.5,
            postgres_pool_min_size=2,
            postgres_pool_max_size=7,
            neo4j_uri="neo4j://projection-host",
            neo4j_user="neo4j",
            neo4j_password="projection-password",
            neo4j_max_pool_size=5,
        )
        assert isinstance(runtime.store._projection, LazyNeo4jProjection)
        assert runtime.store._projection._settings is connections._settings
        assert runtime.atomic_mutations._transactions is transactions
    finally:
        runtime.close()


def test_query_and_mutation_composition_preserve_neo4j_serving_only_boundary() -> None:
    runtime = store._build_runtime(
        Settings(
            store_backend="postgres",
            postgres_dsn="postgresql://runtime@host/emg",
            neo4j_uri="neo4j://projection-host",
        )
    )
    preflight = cast(Any, object())
    try:
        query_application = knowledge_graph_application_dependency(runtime.store)
        mutation_application = mutation_knowledge_graph_application_dependency(
            runtime.store,
            runtime.atomic_mutations,
            preflight,
        )

        assert query_application._graph_store is runtime.store
        assert isinstance(runtime.store._projection, LazyNeo4jProjection)
        assert mutation_application._graph_store is runtime.store
        assert mutation_application._atomic_mutation_execution is runtime.atomic_mutations
        assert runtime.atomic_mutations._transactions is runtime.store._transactions
    finally:
        runtime.close()


def test_runtime_cache_identity_includes_effective_pool_configuration() -> None:
    store.close_store_runtime()
    try:
        first = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            1,
            10,
            None,
            None,
            None,
            10,
        )
        equal = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            1,
            10,
            None,
            None,
            None,
            10,
        )
        different_min = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            2,
            10,
            None,
            None,
            None,
            10,
        )
        different_max = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            1,
            11,
            None,
            None,
            None,
            10,
        )

        assert equal is first
        assert different_min is not first
        assert different_max is not first
    finally:
        store.close_store_runtime()


def test_runtime_cache_identity_includes_effective_neo4j_configuration() -> None:
    store.close_store_runtime()
    try:
        first = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            1,
            10,
            "neo4j://host-a",
            "neo4j",
            Settings(neo4j_password="password-a").neo4j_password,
            10,
        )
        equal = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            1,
            10,
            "neo4j://host-a",
            "neo4j",
            Settings(neo4j_password="password-a").neo4j_password,
            10,
        )
        different_uri = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            1,
            10,
            "neo4j://host-b",
            "neo4j",
            Settings(neo4j_password="password-a").neo4j_password,
            10,
        )
        different_password = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            1,
            10,
            "neo4j://host-a",
            "neo4j",
            Settings(neo4j_password="password-b").neo4j_password,
            10,
        )
        different_pool = store._runtime_singleton_for(
            "postgres",
            "postgresql://runtime@host/emg",
            2.5,
            1,
            10,
            "neo4j://host-a",
            "neo4j",
            Settings(neo4j_password="password-a").neo4j_password,
            11,
        )

        assert equal is first
        assert different_uri is not first
        assert different_password is not first
        assert different_pool is not first
    finally:
        store.close_store_runtime()


def test_knowledge_graph_lifespan_closes_cached_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    class FakePooledConnectionProvider:
        def __init__(self, settings: PersistenceSettings) -> None:
            self.settings = settings

        def close(self) -> None:
            closed.append("postgres")

    class FakeLazyNeo4jProjection:
        def __init__(self, settings: PersistenceSettings) -> None:
            self.settings = settings

        def close(self) -> None:
            closed.append("neo4j")

    monkeypatch.setattr(
        "emg_persistence.postgres.pool.PooledConnectionProvider",
        FakePooledConnectionProvider,
    )
    monkeypatch.setattr(
        "emg_persistence.neo4j.lazy.LazyNeo4jProjection",
        FakeLazyNeo4jProjection,
    )
    monkeypatch.setattr(main, "validate_schema_runtime_configuration", lambda: None)
    store.close_store_runtime()
    store._runtime_singleton_for(
        "postgres",
        "postgresql://runtime@host/emg",
        2.5,
        1,
        10,
        "neo4j://projection-host",
        "neo4j",
        Settings(neo4j_password="projection-password").neo4j_password,
        5,
    )

    try:
        with TestClient(main.create_app()):
            assert closed == []

        assert closed == ["neo4j", "postgres"]
        assert store._active_runtimes == {}
    finally:
        store.close_store_runtime()


def test_startup_migrations_keep_direct_connection_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured: list[PersistenceSettings] = []
    acquired_connection = cast(Connection[Any], object())
    executor = object()

    class FakeDirectConnectionProvider:
        def __init__(self, settings: PersistenceSettings) -> None:
            configured.append(settings)

        @contextmanager
        def acquire(self) -> Iterator[Connection[Any]]:
            yield acquired_connection

    monkeypatch.setattr(migrate, "DirectConnectionProvider", FakeDirectConnectionProvider)
    monkeypatch.setattr(
        migrate,
        "get_settings",
        lambda: Settings(
            store_backend="postgres",
            migration_postgres_dsn="postgresql://migrator@host/emg",
            postgres_connect_timeout_seconds=4.5,
        ),
    )
    monkeypatch.setattr(
        migrate,
        "PostgresMigrationExecutor",
        lambda connection: executor if connection is acquired_connection else pytest.fail(),
    )
    monkeypatch.setattr(
        migrate,
        "run_knowledge_graph_migrations",
        lambda received: [] if received is executor else pytest.fail(),
    )

    migrate.run_startup_migrations()

    assert configured == [
        PersistenceSettings(
            postgres_dsn="postgresql://migrator@host/emg",
            connect_timeout_seconds=4.5,
        )
    ]
