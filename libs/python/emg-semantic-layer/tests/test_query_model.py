"""Query-model tests (FEAT-05-4): selectors, traversal, projection, ordering,
pagination — validation, bounds, and immutability."""

from __future__ import annotations

import pytest
from emg_semantic_layer import (
    NodeSelector,
    Pagination,
    SemanticOrdering,
    SemanticProjection,
    SemanticQuery,
    SemanticTraversal,
    SortDirection,
    SortKey,
    TraversalDirection,
    TraversalStep,
)
from emg_semantic_layer.limits import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_RELATIONSHIP_TYPES_PER_STEP,
    MAX_TRAVERSAL_DEPTH,
)
from pydantic import ValidationError

# --- NodeSelector -----------------------------------------------------------


def test_selector_by_ids_type_or_filter() -> None:
    assert NodeSelector(ids=("p1",)).ids == ("p1",)
    assert NodeSelector(type="Person").type == "Person"


def test_selector_rejects_fully_unbounded() -> None:
    with pytest.raises(ValidationError):
        NodeSelector()  # no ids, no type, no filter -> unbounded scan


def test_selector_rejects_empty_id() -> None:
    with pytest.raises(ValidationError):
        NodeSelector(ids=("",))


def test_selector_is_immutable() -> None:
    s = NodeSelector(type="Person")
    with pytest.raises(ValidationError):
        s.type = "Org"


# --- Traversal --------------------------------------------------------------


def test_traversal_depth_equals_step_count() -> None:
    t = SemanticTraversal(
        steps=(TraversalStep(relationship_types=("A",)), TraversalStep(relationship_types=("B",)))
    )
    assert t.depth == 2


def test_traversal_requires_at_least_one_step() -> None:
    with pytest.raises(ValidationError):
        SemanticTraversal(steps=())


def test_traversal_depth_is_bounded() -> None:
    ok = SemanticTraversal(steps=tuple(TraversalStep() for _ in range(MAX_TRAVERSAL_DEPTH)))
    assert ok.depth == MAX_TRAVERSAL_DEPTH
    with pytest.raises(ValidationError):
        SemanticTraversal(steps=tuple(TraversalStep() for _ in range(MAX_TRAVERSAL_DEPTH + 1)))


def test_traversal_step_direction_default_and_values() -> None:
    assert TraversalStep().direction is TraversalDirection.OUTGOING
    assert TraversalStep(direction=TraversalDirection.BOTH).direction is TraversalDirection.BOTH


def test_traversal_step_relationship_type_fanout_bounded() -> None:
    types = tuple(f"R{i}" for i in range(MAX_RELATIONSHIP_TYPES_PER_STEP + 1))
    with pytest.raises(ValidationError):
        TraversalStep(relationship_types=types)


def test_traversal_step_rejects_empty_relationship_type() -> None:
    with pytest.raises(ValidationError):
        TraversalStep(relationship_types=("",))


# --- Projection -------------------------------------------------------------


def test_projection_default_is_all() -> None:
    assert SemanticProjection().projects_all() is True


def test_projection_rejects_duplicate_or_empty_fields() -> None:
    with pytest.raises(ValidationError):
        SemanticProjection(fields=("a", "a"))
    with pytest.raises(ValidationError):
        SemanticProjection(fields=("",))


# --- Ordering ---------------------------------------------------------------


def test_ordering_requires_keys_and_distinct_fields() -> None:
    SemanticOrdering(keys=(SortKey(field="a"), SortKey(field="b", direction=SortDirection.DESC)))
    with pytest.raises(ValidationError):
        SemanticOrdering(keys=())
    with pytest.raises(ValidationError):
        SemanticOrdering(keys=(SortKey(field="a"), SortKey(field="a")))


# --- Pagination -------------------------------------------------------------


def test_pagination_defaults_and_bounds() -> None:
    assert Pagination().limit == DEFAULT_PAGE_LIMIT
    assert Pagination().offset == 0
    with pytest.raises(ValidationError):
        Pagination(limit=0)
    with pytest.raises(ValidationError):
        Pagination(limit=MAX_PAGE_LIMIT + 1)
    with pytest.raises(ValidationError):
        Pagination(offset=-1)


# --- SemanticQuery ----------------------------------------------------------


def test_query_minimal_has_default_bounded_page() -> None:
    q = SemanticQuery(selector=NodeSelector(type="Person"))
    assert q.pagination.limit == DEFAULT_PAGE_LIMIT
    assert q.traversal_depth == 0


def test_query_is_immutable() -> None:
    q = SemanticQuery(selector=NodeSelector(type="Person"))
    with pytest.raises(ValidationError):
        q.selector = NodeSelector(type="Org")


def test_query_reports_traversal_depth() -> None:
    q = SemanticQuery(
        selector=NodeSelector(type="Person"),
        traversal=SemanticTraversal(steps=(TraversalStep(), TraversalStep())),
    )
    assert q.traversal_depth == 2
