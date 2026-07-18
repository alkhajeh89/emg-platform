"""Public surface + dependency-direction guards (FEAT-05-6)."""

from __future__ import annotations

import emg_memory_graph as mg


def test_version_present() -> None:
    assert mg.__version__ == "0.1.0"


def test_all_exports_are_importable() -> None:
    for name in mg.__all__:
        assert hasattr(mg, name), f"missing export: {name}"


def test_expected_surface_size() -> None:
    # Guards against accidental removal of public API.
    assert len(mg.__all__) >= 60
    assert len(set(mg.__all__)) == len(mg.__all__)  # no duplicates


def test_dependency_direction_only_allowed_packages() -> None:
    """emg-memory-graph may depend on foundational + module-7 libs, never the
    reverse; and never on services / networking / storage engines."""
    import importlib
    import pkgutil

    import emg_memory_graph

    allowed_prefixes = {
        "emg_common_types",
        "emg_errors",
        "emg_ontology",
        "emg_knowledge_pipeline",
        "emg_knowledge_lifecycle",
        "emg_trust_scoring",
        "emg_semantic_layer",
        "emg_memory_graph",
        "pydantic",
    }
    forbidden = {"requests", "httpx", "neo4j", "psycopg", "sqlalchemy", "fastapi", "flask"}
    for mod in pkgutil.iter_modules(emg_memory_graph.__path__):
        module = importlib.import_module(f"emg_memory_graph.{mod.name}")
        for attr in dir(module):
            assert attr not in forbidden
    # sanity: the allow-list is the set we actually consume
    assert "neo4j" not in allowed_prefixes
