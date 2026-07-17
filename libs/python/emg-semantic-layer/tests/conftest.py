"""Shared fixtures for the emg-semantic-layer test suite (FEAT-05-4)."""

from __future__ import annotations

import pytest
from emg_semantic_layer import (
    FilterCondition,
    FilterOperator,
    NodeSelector,
    Pagination,
    SemanticFilter,
    SemanticGraph,
    SemanticNode,
    SemanticOrdering,
    SemanticProjection,
    SemanticQuery,
    SemanticRelationship,
    SemanticTraversal,
    SortKey,
    TraversalStep,
)


@pytest.fixture
def simple_graph() -> SemanticGraph:
    """A small, deterministic three-node graph: two Persons in one Organization."""
    return SemanticGraph(
        nodes=(
            SemanticNode(node_id="p1", type="Person", properties={"name": "Ada"}),
            SemanticNode(node_id="p2", type="Person", properties={"name": "Bo"}),
            SemanticNode(node_id="o1", type="Organization", properties={"name": "Acme"}),
        ),
        relationships=(
            SemanticRelationship(
                relationship_id="r1", type="WORKS_FOR", source_id="p1", target_id="o1"
            ),
            SemanticRelationship(
                relationship_id="r2", type="WORKS_FOR", source_id="p2", target_id="o1"
            ),
        ),
    )


@pytest.fixture
def full_query() -> SemanticQuery:
    """A query exercising every optional clause (used for plan/determinism tests)."""
    return SemanticQuery(
        selector=NodeSelector(type="Person"),
        traversal=SemanticTraversal(
            steps=(TraversalStep(relationship_types=("WORKS_FOR",), target_type="Organization"),)
        ),
        filter=SemanticFilter(
            conditions=(
                FilterCondition(field="status", operator=FilterOperator.EQ, value="active"),
            )
        ),
        projection=SemanticProjection(fields=("name",)),
        ordering=SemanticOrdering(keys=(SortKey(field="name"),)),
        pagination=Pagination(limit=50, offset=0),
    )
