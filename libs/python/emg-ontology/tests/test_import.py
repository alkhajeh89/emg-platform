"""Import, version, and schema-version tests (FEAT-05-1)."""

from __future__ import annotations

import emg_ontology as o


def test_version() -> None:
    assert o.__version__ == "0.1.0"


def test_schema_version_is_pinned() -> None:
    assert o.ONTOLOGY_SCHEMA_VERSION == 1


def test_public_surface_is_exported() -> None:
    for name in (
        "Entity",
        "Actor",
        "Artifact",
        "Event",
        "Relationship",
        "ProvenanceReference",
        "validate_entity",
        "validate_relationship",
        "build_descriptor",
        "descriptor_hash",
        "ENTITY_REGISTRY",
        "RELATIONSHIP_CATALOG",
    ):
        assert hasattr(o, name), name


def test_registry_counts() -> None:
    # 7 organizational + 6 risk&safety + 3 module-6 reference types.
    assert len(o.ENTITY_REGISTRY) == 16
    assert len(o.RELATIONSHIP_CATALOG) == 8
