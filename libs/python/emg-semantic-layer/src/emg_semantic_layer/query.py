"""The deterministic, storage-independent query model (FEAT-05-4).

A `SemanticQuery` is an **immutable, self-validating description of intent** —
which nodes to start from, how to traverse, how to filter, project, order, and
page — with **no execution semantics of its own**. It defines *what* a conforming
storage binding must return, not *how* to fetch it, so the same query is valid
against any backend (a future Neo4j binding, an in-memory test double, etc.).

Every model is frozen and validated at construction, so a malformed query is
rejected immediately. Every user-controlled collection is bounded in *size* as
well as in nesting/depth (`limits.py`): traversal depth, page limit and offset,
selector-id count, relationship-type fan-out, filter width and nesting,
projection-field count, and ordering-key count all have hard caps. Operators come
from closed enums (`enums.py`), values are plain scalars, and every identifier/
label is validated by `ensure_safe_label` (`validation.py`) — there is no place
for arbitrary code, an injection payload, or a control/bidi-spoofed identifier.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import SortDirection, TraversalDirection
from .filters import SemanticFilter
from .limits import (
    DEFAULT_PAGE_LIMIT,
    MAX_ORDERING_KEYS,
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    MAX_PROJECTION_FIELDS,
    MAX_RELATIONSHIP_TYPES_PER_STEP,
    MAX_SELECTOR_IDS,
    MAX_TRAVERSAL_DEPTH,
    MIN_PAGE_LIMIT,
)
from .validation import SafeLabel


class NodeSelector(BaseModel):
    """The query root: the starting set of nodes. Selects by explicit ids, by
    type, or by both, optionally narrowed by a filter. A fully-empty selector is
    rejected so a query can never request an unbounded full scan, and the id list
    is bounded by `MAX_SELECTOR_IDS`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ids: tuple[SafeLabel, ...] = ()
    type: SafeLabel | None = None
    filter: SemanticFilter | None = None

    @model_validator(mode="after")
    def _require_a_bound(self) -> NodeSelector:
        if not self.ids and self.type is None and self.filter is None:
            raise ValueError(
                "NodeSelector must constrain by ids, type, and/or filter "
                "(an unbounded selection is not permitted)"
            )
        if len(self.ids) > MAX_SELECTOR_IDS:
            raise ValueError(
                f"NodeSelector names {len(self.ids)} ids; maximum is {MAX_SELECTOR_IDS}"
            )
        return self


class TraversalStep(BaseModel):
    """One hop: follow the named relationship type(s) in a direction, optionally
    constraining the reached nodes by type and/or filter. An empty
    `relationship_types` follows any relationship type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: TraversalDirection = TraversalDirection.OUTGOING
    relationship_types: tuple[SafeLabel, ...] = ()
    target_type: SafeLabel | None = None
    filter: SemanticFilter | None = None

    @model_validator(mode="after")
    def _validate_relationship_types(self) -> TraversalStep:
        if len(self.relationship_types) > MAX_RELATIONSHIP_TYPES_PER_STEP:
            raise ValueError(
                f"a traversal step names {len(self.relationship_types)} relationship types; "
                f"maximum is {MAX_RELATIONSHIP_TYPES_PER_STEP}"
            )
        return self


class SemanticTraversal(BaseModel):
    """An ordered sequence of hops from the selected roots. Depth equals the
    number of steps and is hard-bounded by `MAX_TRAVERSAL_DEPTH`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: tuple[TraversalStep, ...]

    @model_validator(mode="after")
    def _validate_depth(self) -> SemanticTraversal:
        if len(self.steps) == 0:
            raise ValueError("a traversal must have at least one step")
        if len(self.steps) > MAX_TRAVERSAL_DEPTH:
            raise ValueError(
                f"traversal depth {len(self.steps)} exceeds maximum {MAX_TRAVERSAL_DEPTH}"
            )
        return self

    @property
    def depth(self) -> int:
        return len(self.steps)


class SemanticProjection(BaseModel):
    """Selects which node fields/properties a result carries. Empty `fields`
    means "the whole node". `include_relationships` controls whether traversed
    relationships are returned alongside nodes. The field list is bounded by
    `MAX_PROJECTION_FIELDS`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: tuple[SafeLabel, ...] = ()
    include_relationships: bool = True

    @model_validator(mode="after")
    def _validate_fields(self) -> SemanticProjection:
        if len(self.fields) > MAX_PROJECTION_FIELDS:
            raise ValueError(
                f"projection names {len(self.fields)} fields; maximum is {MAX_PROJECTION_FIELDS}"
            )
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("projection fields must be unique")
        return self

    def projects_all(self) -> bool:
        return not self.fields


class SortKey(BaseModel):
    """One ordering key: a field and a direction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: SafeLabel
    direction: SortDirection = SortDirection.ASC


class SemanticOrdering(BaseModel):
    """A total, deterministic ordering: an ordered tuple of sort keys applied
    left-to-right. Duplicate fields are rejected so the order is unambiguous; the
    key count is bounded by `MAX_ORDERING_KEYS`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    keys: tuple[SortKey, ...]

    @model_validator(mode="after")
    def _validate_keys(self) -> SemanticOrdering:
        if len(self.keys) == 0:
            raise ValueError("ordering must have at least one sort key")
        if len(self.keys) > MAX_ORDERING_KEYS:
            raise ValueError(
                f"ordering names {len(self.keys)} keys; maximum is {MAX_ORDERING_KEYS}"
            )
        fields = [k.field for k in self.keys]
        if len(fields) != len(set(fields)):
            raise ValueError("ordering sort keys must reference distinct fields")
        return self


class Pagination(BaseModel):
    """A bounded result window. `limit` is constrained to `[MIN_PAGE_LIMIT,
    MAX_PAGE_LIMIT]` and `offset` to `[0, MAX_PAGE_OFFSET]`, so neither an
    unbounded page nor an arbitrarily deep offset is expressible."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=MIN_PAGE_LIMIT, le=MAX_PAGE_LIMIT)
    offset: int = Field(default=0, ge=0, le=MAX_PAGE_OFFSET)


class SemanticQuery(BaseModel):
    """A complete, immutable, deterministic query. Composes a root selection with
    an optional traversal, a post-traversal filter, a projection, an ordering,
    and a bounded page. Ordering without pagination is still deterministic; an
    unbounded query is rejected because pagination is always present (a default
    bounded page is supplied)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: NodeSelector
    traversal: SemanticTraversal | None = None
    filter: SemanticFilter | None = None
    projection: SemanticProjection | None = None
    ordering: SemanticOrdering | None = None
    pagination: Pagination = Field(default_factory=Pagination)

    @property
    def traversal_depth(self) -> int:
        return self.traversal.depth if self.traversal is not None else 0
