"""Filtering model (FEAT-05-4).

A filter is a **pure data structure**: a leaf `FilterCondition` names a field, a
closed-enum operator, and a plain value; a `SemanticFilter` combines conditions
and sub-filters with a boolean operator. There are no callables, no raw query
fragments, and no free-form strings interpreted as code — so a filter can carry
no injection payload and trigger no arbitrary execution. Nesting depth is bounded
(`MAX_FILTER_DEPTH`). All models are frozen and validated at construction, so a
malformed filter is rejected immediately.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from .enums import COLLECTION_OPERATORS, NULLARY_OPERATORS, BooleanOperator, FilterOperator
from .graph import PropertyValue
from .limits import MAX_FILTER_CONDITIONS, MAX_FILTER_DEPTH, MAX_FILTER_GROUPS
from .validation import SafeLabel

# A condition's value is either a single scalar, an ordered collection of scalars
# (for IN / NOT_IN), or absent (for the nullary EXISTS / NOT_EXISTS operators).
ConditionValue = PropertyValue | tuple[PropertyValue, ...]

# Operators that require a non-null scalar operand (ordering and text tests).
_NON_NULL_SCALAR_OPERATORS: frozenset[FilterOperator] = frozenset(
    {
        FilterOperator.LT,
        FilterOperator.LTE,
        FilterOperator.GT,
        FilterOperator.GTE,
        FilterOperator.CONTAINS,
        FilterOperator.STARTS_WITH,
    }
)

# Text operators require a string operand.
_STRING_OPERATORS: frozenset[FilterOperator] = frozenset(
    {FilterOperator.CONTAINS, FilterOperator.STARTS_WITH}
)


class FilterCondition(BaseModel):
    """A single leaf predicate: ``<field> <operator> <value>``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: SafeLabel
    operator: FilterOperator
    value: ConditionValue = None

    @model_validator(mode="after")
    def _validate_operand(self) -> FilterCondition:
        op = self.operator
        if op in NULLARY_OPERATORS:
            if self.value is not None:
                raise ValueError(f"operator {op.value} takes no value")
            return self
        if op in COLLECTION_OPERATORS:
            if not isinstance(self.value, tuple) or len(self.value) == 0:
                raise ValueError(f"operator {op.value} requires a non-empty collection value")
            return self
        # All remaining operators take a single scalar (never a collection).
        if isinstance(self.value, tuple):
            raise ValueError(f"operator {op.value} does not take a collection value")
        if op in _NON_NULL_SCALAR_OPERATORS and self.value is None:
            raise ValueError(f"operator {op.value} requires a non-null value")
        if op in _STRING_OPERATORS and not isinstance(self.value, str):
            raise ValueError(f"operator {op.value} requires a string value")
        return self


class SemanticFilter(BaseModel):
    """A boolean combination of conditions and nested filters. An ``AND``/``OR``
    group with no children matches everything (an explicit "match all"); a
    ``NOT`` group must wrap exactly one child."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator: BooleanOperator = BooleanOperator.AND
    conditions: tuple[FilterCondition, ...] = ()
    groups: tuple[SemanticFilter, ...] = ()

    @model_validator(mode="after")
    def _validate_structure(self) -> SemanticFilter:
        child_count = len(self.conditions) + len(self.groups)
        if self.operator is BooleanOperator.NOT and child_count != 1:
            raise ValueError("NOT filter must wrap exactly one condition or group")
        if len(self.conditions) > MAX_FILTER_CONDITIONS:
            raise ValueError(
                f"filter has {len(self.conditions)} conditions; maximum is {MAX_FILTER_CONDITIONS}"
            )
        if len(self.groups) > MAX_FILTER_GROUPS:
            raise ValueError(
                f"filter has {len(self.groups)} sub-groups; maximum is {MAX_FILTER_GROUPS}"
            )
        if self.depth > MAX_FILTER_DEPTH:
            raise ValueError(
                f"filter nesting depth {self.depth} exceeds maximum {MAX_FILTER_DEPTH}"
            )
        return self

    @property
    def depth(self) -> int:
        """Nesting depth: 1 for a flat group, +1 per level of nested groups."""
        if not self.groups:
            return 1
        return 1 + max(g.depth for g in self.groups)

    def is_match_all(self) -> bool:
        """True for an empty AND/OR group (imposes no constraint)."""
        return self.operator is not BooleanOperator.NOT and not self.conditions and not self.groups
