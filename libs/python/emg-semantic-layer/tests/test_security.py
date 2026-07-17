"""Security tests (FEAT-05-4): immutable query models, deterministic execution
model, structural validation, bounded traversal, malformed-query rejection, no
arbitrary code execution, and no injection surface."""

from __future__ import annotations

import emg_semantic_layer as sl
import pytest
from emg_errors import ValidationError as EMGValidationError
from emg_semantic_layer import (
    FilterCondition,
    FilterOperator,
    NodeSelector,
    Pagination,
    SemanticQuery,
    SemanticQueryError,
    SemanticTraversal,
    TraversalStep,
    plan,
)
from emg_semantic_layer.limits import MAX_TRAVERSAL_DEPTH
from pydantic import ValidationError

# --- no arbitrary code execution / no injection surface ---------------------


def test_operator_must_be_a_closed_enum_member() -> None:
    """An operator cannot be an arbitrary string (no free-form operator injection)."""
    with pytest.raises(ValidationError):
        FilterCondition(field="x", operator="; DROP TABLE", value=1)  # type: ignore[arg-type]


def test_injection_like_value_is_inert_data() -> None:
    """A malicious-looking string is stored verbatim as data and never interpreted;
    it appears only as inert text in the (non-executable) plan detail."""
    payload = "1; MATCH (n) DETACH DELETE n //"
    q = SemanticQuery(
        selector=NodeSelector(
            filter=sl.SemanticFilter(
                conditions=(
                    FilterCondition(field="name", operator=FilterOperator.EQ, value=payload),
                )
            )
        )
    )
    cond = q.selector.filter.conditions[0]  # type: ignore[union-attr]
    assert cond.value == payload  # preserved as data, not executed
    # The plan is a description only; nothing is evaluated.
    assert all(isinstance(s.detail, str) for s in plan(q).steps)


def test_property_value_cannot_be_a_callable() -> None:
    with pytest.raises(ValidationError):
        FilterCondition(field="x", operator=FilterOperator.EQ, value=len)  # type: ignore[arg-type]


def test_query_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SemanticQuery(selector=NodeSelector(type="Person"), rogue="x")  # type: ignore[call-arg]


# --- immutability -----------------------------------------------------------


def test_all_query_parts_are_frozen() -> None:
    q = SemanticQuery(selector=NodeSelector(type="Person"), pagination=Pagination(limit=5))
    with pytest.raises(ValidationError):
        q.pagination = Pagination(limit=6)
    with pytest.raises(ValidationError):
        q.pagination.limit = 6


# --- deterministic execution model ------------------------------------------


def test_execution_model_is_deterministic(full_query: SemanticQuery) -> None:
    assert plan(full_query).model_dump() == plan(full_query).model_dump()


# --- bounded traversal + malformed-query rejection --------------------------


def test_traversal_depth_bounded_at_construction() -> None:
    with pytest.raises(ValidationError):
        SemanticTraversal(steps=tuple(TraversalStep() for _ in range(MAX_TRAVERSAL_DEPTH + 1)))


def test_planner_rejects_over_deep_traversal_that_bypassed_construction() -> None:
    """Defence in depth: even a query assembled via model_construct (which skips
    validation) is rejected by the planner with a typed SemanticQueryError."""
    over_deep = SemanticTraversal.model_construct(
        steps=tuple(TraversalStep() for _ in range(MAX_TRAVERSAL_DEPTH + 1))
    )
    q = SemanticQuery.model_construct(
        selector=NodeSelector(type="Person"),
        traversal=over_deep,
        filter=None,
        projection=None,
        ordering=None,
        pagination=Pagination(),
    )
    with pytest.raises(SemanticQueryError):
        plan(q)


def test_semantic_query_error_is_an_emg_validation_error() -> None:
    err = SemanticQueryError("bad")
    assert isinstance(err, EMGValidationError)
    assert err.error_code == "SEMANTIC_QUERY_ERROR"


def test_unbounded_selector_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NodeSelector()
