"""Closed enumerations for the Semantic Layer query model (FEAT-05-4).

Every operator, direction, and boolean combinator is a **closed enum**, never a
caller-supplied string, callable, or expression. This is a deliberate security
property: a query is pure structured data built from a fixed vocabulary, so there
is no place for arbitrary code, a raw query fragment, or an injection payload to
enter the model. A storage binding maps these enum members onto its own
parameterised query API; it must never string-concatenate them into a query.
"""

from __future__ import annotations

from enum import Enum


class TraversalDirection(str, Enum):
    """The direction a traversal step follows a relationship, relative to the
    node the step starts from."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class FilterOperator(str, Enum):
    """The comparison a single filter condition applies to one field. The value
    a condition carries is plain data; the operator is one of these members
    only."""

    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"


# Operators that take no value (they test only presence/absence of the field).
NULLARY_OPERATORS: frozenset[FilterOperator] = frozenset(
    {FilterOperator.EXISTS, FilterOperator.NOT_EXISTS}
)

# Operators whose value is a collection (membership tests).
COLLECTION_OPERATORS: frozenset[FilterOperator] = frozenset(
    {FilterOperator.IN, FilterOperator.NOT_IN}
)


class BooleanOperator(str, Enum):
    """How the conditions/sub-filters of a `SemanticFilter` combine."""

    AND = "and"
    OR = "or"
    NOT = "not"


class SortDirection(str, Enum):
    """Ordering direction for a sort key."""

    ASC = "asc"
    DESC = "desc"
