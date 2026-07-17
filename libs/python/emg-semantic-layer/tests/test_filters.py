"""Filter-model tests (FEAT-05-4): operand validation, nesting bounds, structure."""

from __future__ import annotations

import pytest
from emg_semantic_layer import (
    BooleanOperator,
    FilterCondition,
    FilterOperator,
    SemanticFilter,
)
from emg_semantic_layer.limits import MAX_FILTER_DEPTH
from pydantic import ValidationError


def test_scalar_condition() -> None:
    c = FilterCondition(field="status", operator=FilterOperator.EQ, value="active")
    assert c.value == "active"


def test_nullary_operator_rejects_a_value() -> None:
    FilterCondition(field="x", operator=FilterOperator.EXISTS)  # ok, no value
    with pytest.raises(ValidationError):
        FilterCondition(field="x", operator=FilterOperator.EXISTS, value="v")


def test_collection_operator_requires_non_empty_tuple() -> None:
    FilterCondition(field="x", operator=FilterOperator.IN, value=("a", "b"))
    with pytest.raises(ValidationError):
        FilterCondition(field="x", operator=FilterOperator.IN, value="scalar")
    with pytest.raises(ValidationError):
        FilterCondition(field="x", operator=FilterOperator.IN, value=())


def test_scalar_operator_rejects_collection() -> None:
    with pytest.raises(ValidationError):
        FilterCondition(field="x", operator=FilterOperator.EQ, value=("a", "b"))


def test_comparison_operator_requires_non_null() -> None:
    with pytest.raises(ValidationError):
        FilterCondition(field="x", operator=FilterOperator.GT, value=None)


def test_text_operator_requires_string() -> None:
    FilterCondition(field="x", operator=FilterOperator.CONTAINS, value="ab")
    with pytest.raises(ValidationError):
        FilterCondition(field="x", operator=FilterOperator.CONTAINS, value=5)


def test_condition_is_immutable() -> None:
    c = FilterCondition(field="x", operator=FilterOperator.EQ, value=1)
    with pytest.raises(ValidationError):
        c.value = 2


def test_empty_and_group_is_match_all() -> None:
    f = SemanticFilter()
    assert f.operator is BooleanOperator.AND
    assert f.is_match_all() is True
    assert f.depth == 1


def test_not_group_requires_exactly_one_child() -> None:
    inner = FilterCondition(field="x", operator=FilterOperator.EQ, value=1)
    SemanticFilter(operator=BooleanOperator.NOT, conditions=(inner,))  # ok
    with pytest.raises(ValidationError):
        SemanticFilter(operator=BooleanOperator.NOT)  # zero children
    with pytest.raises(ValidationError):
        SemanticFilter(
            operator=BooleanOperator.NOT,
            conditions=(inner, inner),  # two children
        )


def test_nested_filter_depth_is_computed() -> None:
    leaf = FilterCondition(field="x", operator=FilterOperator.EQ, value=1)
    lvl1 = SemanticFilter(conditions=(leaf,))
    lvl2 = SemanticFilter(groups=(lvl1,))
    lvl3 = SemanticFilter(groups=(lvl2,))
    assert lvl1.depth == 1
    assert lvl2.depth == 2
    assert lvl3.depth == 3


def test_filter_nesting_is_bounded() -> None:
    leaf = FilterCondition(field="x", operator=FilterOperator.EQ, value=1)
    node = SemanticFilter(conditions=(leaf,))
    # Build exactly to the maximum depth (allowed), then one deeper (rejected).
    for _ in range(MAX_FILTER_DEPTH - 1):
        node = SemanticFilter(groups=(node,))
    assert node.depth == MAX_FILTER_DEPTH
    with pytest.raises(ValidationError):
        SemanticFilter(groups=(node,))  # depth MAX+1
