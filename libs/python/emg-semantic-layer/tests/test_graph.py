"""Graph value-object tests (FEAT-05-4): construction, immutability, lookups."""

from __future__ import annotations

import pytest
from emg_common_types import Classification
from emg_semantic_layer import SemanticGraph, SemanticNode, SemanticRelationship
from pydantic import ValidationError


def test_node_construction_and_defaults() -> None:
    n = SemanticNode(node_id="p1", type="Person")
    assert n.node_id == "p1"
    assert n.type == "Person"
    assert n.classification is None
    assert dict(n.properties) == {}


def test_node_accepts_classification_and_scalar_properties() -> None:
    n = SemanticNode(
        node_id="p1",
        type="Person",
        classification=Classification.INTERNAL,
        properties={"name": "Ada", "age": 40, "active": True, "score": 1.5, "note": None},
    )
    assert n.classification is Classification.INTERNAL
    assert n.properties["age"] == 40


def test_node_properties_are_sorted_for_determinism() -> None:
    n = SemanticNode(node_id="p1", type="Person", properties={"b": 1, "a": 2})
    assert list(n.properties.keys()) == ["a", "b"]


def test_node_is_immutable() -> None:
    n = SemanticNode(node_id="p1", type="Person")
    with pytest.raises(ValidationError):
        n.node_id = "p2"


def test_node_rejects_empty_ids_and_types() -> None:
    with pytest.raises(ValidationError):
        SemanticNode(node_id="", type="Person")
    with pytest.raises(ValidationError):
        SemanticNode(node_id="p1", type="")


def test_node_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SemanticNode(node_id="p1", type="Person", injected="x")  # type: ignore[call-arg]


def test_node_rejects_non_scalar_property() -> None:
    with pytest.raises(ValidationError):
        SemanticNode(node_id="p1", type="Person", properties={"bad": {"nested": 1}})  # type: ignore[dict-item]


def test_graph_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValidationError):
        SemanticGraph(
            nodes=(
                SemanticNode(node_id="p1", type="Person"),
                SemanticNode(node_id="p1", type="Person"),
            )
        )


def test_graph_rejects_duplicate_relationship_ids() -> None:
    with pytest.raises(ValidationError):
        SemanticGraph(
            relationships=(
                SemanticRelationship(relationship_id="r1", type="X", source_id="a", target_id="b"),
                SemanticRelationship(relationship_id="r1", type="Y", source_id="a", target_id="c"),
            )
        )


def test_graph_lookup_helpers(simple_graph: SemanticGraph) -> None:
    assert simple_graph.node("p1") is not None
    assert simple_graph.node("missing") is None
    assert {r.relationship_id for r in simple_graph.relationships_of("o1")} == {"r1", "r2"}
    assert [n.node_id for n in simple_graph.neighbors("o1")] == ["p1", "p2"]
    assert [n.node_id for n in simple_graph.neighbors("p1")] == ["o1"]


def test_graph_helpers_are_deterministic(simple_graph: SemanticGraph) -> None:
    assert simple_graph.neighbors("o1") == simple_graph.neighbors("o1")
