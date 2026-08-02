"""Package import surface and version (Sprint 1)."""

from __future__ import annotations

import emg_persistence as pkg


def test_version() -> None:
    assert pkg.__version__ == "0.1.0"


def test_public_api_exports() -> None:
    expected = {
        "PersistenceSettings",
        "build_graph_store",
        "PersistenceError",
        "PersistenceConflictError",
        "EvidenceLedgerIntegrityError",
        "ProjectionLagError",
        "PostgresNeo4jGraphStore",
    }
    assert expected.issubset(set(pkg.__all__))
    for name in expected:
        assert hasattr(pkg, name), name


def test_submodules_import() -> None:
    from emg_persistence import config, errors, factory

    assert config.PersistenceSettings is pkg.PersistenceSettings
    assert errors.PersistenceError is pkg.PersistenceError
    assert factory.build_graph_store is pkg.build_graph_store
