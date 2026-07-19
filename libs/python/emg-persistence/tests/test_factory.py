"""build_graph_store: backend selection / dependency injection (Sprint 1)."""

from __future__ import annotations

import pytest
from emg_persistence import PersistenceSettings, build_graph_store
from emg_platform_core import GraphStore, InMemoryGraphStore


def test_default_returns_in_memory_graphstore() -> None:
    store = build_graph_store()
    assert isinstance(store, InMemoryGraphStore)
    assert isinstance(store, GraphStore)  # satisfies the unchanged Phase 1 port


def test_explicit_unconfigured_settings_return_in_memory() -> None:
    store = build_graph_store(PersistenceSettings())
    assert isinstance(store, InMemoryGraphStore)


def test_configured_persistence_hits_unimplemented_placeholder() -> None:
    # PostgreSQL configured => persistence requested, but the persistent backend
    # is a Sprint 1 scaffold placeholder (delivered in a later sprint). The
    # factory delegates to the placeholder, which raises NotImplementedError —
    # a neutral "structure, not behavior" signal rather than a fixed runtime
    # policy.
    settings = PersistenceSettings(postgres_dsn="postgresql://u@h/db")
    with pytest.raises(NotImplementedError):
        build_graph_store(settings)


def test_neo4j_only_still_in_memory() -> None:
    # Neo4j is projection-only (ADR-1); without postgres_dsn persistence is not
    # considered configured, so the in-memory store is returned.
    store = build_graph_store(PersistenceSettings(neo4j_uri="neo4j://h"))
    assert isinstance(store, InMemoryGraphStore)


def test_factory_returns_fresh_instances() -> None:
    assert build_graph_store() is not build_graph_store()
