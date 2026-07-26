"""Immutable command/query contracts for knowledge-graph application workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from emg_common_types import Classification
from emg_memory_graph import MAX_TRAVERSAL_DEPTH as _MAX_TRAVERSAL_DEPTH
from emg_memory_graph import EdgeDirection, MetadataItem, ensure_safe_label
from emg_memory_graph.limits import MAX_LABEL_LENGTH
from emg_ontology import Entity, Relationship
from emg_platform_core import (
    DEFAULT_REVISION_LIST_LIMIT,
    MAX_REVISION_LIST_LIMIT,
    PrincipalRef,
    TenantId,
)
from pydantic import ValidationError as _PydanticValidationError

from .errors import (
    InvalidHistoryQueryError,
    InvalidQueryError,
    InvalidRevisionCommandError,
    InvalidTemporalFilterError,
    PathDepthExceededError,
    QueryLimitExceededError,
)

# --- Query safety limits (ADR-024 §14, §15, §18) ------------------------------
# Fixed, code-level ceilings — not runtime configuration (ADR-024 §18). Never
# redefined against a floating value: MAX_TRAVERSAL_DEPTH is re-exported
# unchanged from emg_memory_graph.limits, exactly as ADR-024 §15/§23 mandates
# ("reusing the existing constants directly ... not redefining them locally"),
# rather than restated as a fresh literal here.
MAX_QUERY_PAGE_SIZE = 200
MAX_QUERY_PROPERTY_PREDICATES = 8
MAX_TRAVERSAL_DEPTH = _MAX_TRAVERSAL_DEPTH


def _validate_label(value: object, *, field: str) -> None:
    """Validate `value` against the same constraints `SafeLabel` enforces
    (non-empty, bounded length, no control/bidi characters) — the "existing
    domain constraints" ids and cursors must satisfy (ADR-024 §4)."""
    if not isinstance(value, str):
        raise InvalidQueryError(f"{field} must be a string")
    if len(value) > MAX_LABEL_LENGTH:
        raise InvalidQueryError(f"{field} exceeds max length {MAX_LABEL_LENGTH}: {value!r}")
    try:
        ensure_safe_label(value)
    except ValueError as exc:
        raise InvalidQueryError(f"{field} is not a valid id/label: {exc}") from exc


def _validate_limit(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidQueryError("limit must be an int")
    if value < 1:
        raise InvalidQueryError(f"limit must be >= 1: {value!r}")
    if value > MAX_QUERY_PAGE_SIZE:
        raise QueryLimitExceededError(f"limit must be <= {MAX_QUERY_PAGE_SIZE}: {value!r}")


def _validate_confidence(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidQueryError("confidence must be a number")
    if not (0.0 <= float(value) <= 1.0):
        raise InvalidQueryError(f"confidence must be in [0.0, 1.0]: {value!r}")


def _validate_valid_at(value: object) -> None:
    """Reject a missing or timezone-naive ``valid_at`` before any store
    interaction (ADR-024 §13)."""
    if not isinstance(value, datetime):
        raise InvalidTemporalFilterError("valid_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidTemporalFilterError("valid_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class BuildRevisionCommand:
    """Validated ontology input for one tenant-scoped revision build."""

    tenant: TenantId
    principal: PrincipalRef
    entities: tuple[Entity, ...]
    relationships: tuple[Relationship, ...]
    as_of: datetime

    def validate(self) -> None:
        """Validate application-command invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidRevisionCommandError("tenant must be a TenantId")
        if not isinstance(self.principal, PrincipalRef):
            raise InvalidRevisionCommandError("principal must be a PrincipalRef")
        if not isinstance(self.entities, tuple) or not all(
            isinstance(item, Entity) for item in self.entities
        ):
            raise InvalidRevisionCommandError("entities must be a tuple of ontology Entity objects")
        if not isinstance(self.relationships, tuple) or not all(
            isinstance(item, Relationship) for item in self.relationships
        ):
            raise InvalidRevisionCommandError(
                "relationships must be a tuple of ontology Relationship objects"
            )
        if not self.entities and not self.relationships:
            raise InvalidRevisionCommandError(
                "revision command must contain at least one entity or relationship"
            )
        if not isinstance(self.as_of, datetime):
            raise InvalidRevisionCommandError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise InvalidRevisionCommandError("as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ListRevisionsQuery:
    """A tenant's revision history, newest first, bounded and cursor-paged
    (ADR-023 §12, §13). Read-only: deliberately carries no ``PrincipalRef``."""

    tenant: TenantId
    limit: int = DEFAULT_REVISION_LIST_LIMIT
    before_revision_number: int | None = None

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidHistoryQueryError("tenant must be a TenantId")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise InvalidHistoryQueryError("limit must be an int")
        if not (1 <= self.limit <= MAX_REVISION_LIST_LIMIT):
            raise InvalidHistoryQueryError(
                f"limit must be in [1, {MAX_REVISION_LIST_LIMIT}]: {self.limit!r}"
            )
        if self.before_revision_number is not None:
            if isinstance(self.before_revision_number, bool) or not isinstance(
                self.before_revision_number, int
            ):
                raise InvalidHistoryQueryError("before_revision_number must be an int")
            if self.before_revision_number < 1:
                raise InvalidHistoryQueryError("before_revision_number must be >= 1")


@dataclass(frozen=True, slots=True)
class GetRevisionQuery:
    """One tenant's historical revision, identified by number (ADR-023 §12).
    Read-only: deliberately carries no ``PrincipalRef``."""

    tenant: TenantId
    revision_number: int

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidHistoryQueryError("tenant must be a TenantId")
        if isinstance(self.revision_number, bool) or not isinstance(self.revision_number, int):
            raise InvalidHistoryQueryError("revision_number must be an int")
        if self.revision_number < 1:
            raise InvalidHistoryQueryError("revision_number must be >= 1")


@dataclass(frozen=True, slots=True)
class CompareRevisionsQuery:
    """A diff between two of a tenant's historical revisions (ADR-023 §12,
    §14). Self-comparison (``from == to``) and reverse comparison
    (``from > to``) are both valid and are not rejected. Read-only:
    deliberately carries no ``PrincipalRef``."""

    tenant: TenantId
    from_revision_number: int
    to_revision_number: int

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidHistoryQueryError("tenant must be a TenantId")
        for name, value in (
            ("from_revision_number", self.from_revision_number),
            ("to_revision_number", self.to_revision_number),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidHistoryQueryError(f"{name} must be an int")
            if value < 1:
                raise InvalidHistoryQueryError(f"{name} must be >= 1")


@dataclass(frozen=True, slots=True)
class RestoreRevisionCommand:
    """Restore a tenant's historical revision by committing it as the next
    immutable revision (ADR-023 §12, §15). Carries no ``as_of`` — no concrete
    domain meaning was identified for a caller-supplied restore timestamp; the
    commit's own ``committed_at`` is server-clock, not caller-supplied."""

    tenant: TenantId
    principal: PrincipalRef
    source_revision_number: int

    def validate(self) -> None:
        """Validate application-command invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidRevisionCommandError("tenant must be a TenantId")
        if not isinstance(self.principal, PrincipalRef):
            raise InvalidRevisionCommandError("principal must be a PrincipalRef")
        if isinstance(self.source_revision_number, bool) or not isinstance(
            self.source_revision_number, int
        ):
            raise InvalidRevisionCommandError("source_revision_number must be an int")
        if self.source_revision_number < 1:
            raise InvalidRevisionCommandError("source_revision_number must be >= 1")


# --- Query engine application contracts (ADR-024, Sprint 7.3 Phase 1) --------
#
# Phase 1 scope only: command models, validation, and safety limits. No
# orchestration method calls these yet — GraphStore/GraphRevisionReader are
# not queried by anything in this module (ADR-024 §25).


class NeighborDirection(str, Enum):
    """Which incident edges to traverse from a subject node (ADR-024 §10
    F/G/H). Deliberately distinct from ``emg_memory_graph.EdgeDirection``,
    which describes an edge's own directed/undirected *storage* semantics,
    not a traversal mode relative to a subject node."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class GraphQueryScope:
    """Which tenant's graph, and which immutable snapshot of it, a query runs
    against (ADR-024 §11). Contains no timestamp selector: selecting a
    revision by wall-clock time is explicitly deferred (ADR-024 §20.10). This
    is the *revision axis* only — a query command's own ``valid_at`` field, if
    any, is the independent, composable *domain temporal axis* (ADR-024 §11)."""

    tenant: TenantId
    revision_number: int | None = None

    def validate(self) -> None:
        """Validate scope invariants without opening a transaction."""
        if not isinstance(self.tenant, TenantId):
            raise InvalidQueryError("tenant must be a TenantId")
        if self.revision_number is not None:
            if isinstance(self.revision_number, bool) or not isinstance(self.revision_number, int):
                raise InvalidQueryError("revision_number must be an int")
            if self.revision_number < 1:
                raise InvalidQueryError("revision_number must be >= 1")


@dataclass(frozen=True, slots=True)
class MetadataPredicate:
    """One exact metadata key/value match (ADR-024 §12). Metadata remains a
    bounded, schemaless string key/value container — never strongly typed;
    key/value validity is delegated to the existing domain
    ``MetadataItem`` type rather than reimplemented here."""

    key: str
    value: str

    def validate(self) -> None:
        """Validate key/value using the existing domain metadata limits and
        validation types (``MetadataItem``), without opening a transaction."""
        if not isinstance(self.key, str) or not isinstance(self.value, str):
            raise InvalidQueryError("metadata predicate key/value must be strings")
        try:
            MetadataItem(key=self.key, value=self.value)
        except _PydanticValidationError as exc:
            raise InvalidQueryError(f"invalid metadata predicate: {exc}") from exc


@dataclass(frozen=True, slots=True)
class GetEntityQuery:
    """Entity lookup by canonical node id, current head or one historical
    revision (ADR-024 §9, §10.A). Read-only: deliberately carries no
    ``PrincipalRef``."""

    scope: GraphQueryScope
    node_id: str

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        self.scope.validate()
        _validate_label(self.node_id, field="node_id")


@dataclass(frozen=True, slots=True)
class ListEntitiesQuery:
    """List/filter entities by type and/or exact scalar/metadata properties
    (ADR-024 §10.B, §10.C, §12). One combined shape covers both plain
    type-listing and exact property matching — every filter is optional and
    additive; the scalar fields are exactly those ADR-024 §12 permits
    (``node_type``, ``source``, ``confidence``, ``classification``), plus
    exact ``metadata`` key/value predicates. Read-only: deliberately carries
    no ``PrincipalRef``."""

    scope: GraphQueryScope
    node_type: str | None = None
    source: str | None = None
    confidence: float | None = None
    classification: Classification | None = None
    metadata_predicates: tuple[MetadataPredicate, ...] = ()
    limit: int = MAX_QUERY_PAGE_SIZE
    before_node_id: str | None = None

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        self.scope.validate()
        if self.node_type is not None:
            _validate_label(self.node_type, field="node_type")
        if self.source is not None:
            _validate_label(self.source, field="source")
        if self.confidence is not None:
            _validate_confidence(self.confidence)
        if self.classification is not None and not isinstance(self.classification, Classification):
            raise InvalidQueryError("classification must be a Classification")
        if not isinstance(self.metadata_predicates, tuple) or not all(
            isinstance(item, MetadataPredicate) for item in self.metadata_predicates
        ):
            raise InvalidQueryError("metadata_predicates must be a tuple of MetadataPredicate")
        for predicate in self.metadata_predicates:
            predicate.validate()
        predicate_count = sum(
            1
            for value in (self.node_type, self.source, self.confidence, self.classification)
            if value is not None
        ) + len(self.metadata_predicates)
        if predicate_count > MAX_QUERY_PROPERTY_PREDICATES:
            raise QueryLimitExceededError(
                f"at most {MAX_QUERY_PROPERTY_PREDICATES} exact property predicates "
                f"are allowed per query: {predicate_count!r}"
            )
        _validate_limit(self.limit)
        if self.before_node_id is not None:
            _validate_label(self.before_node_id, field="before_node_id")


@dataclass(frozen=True, slots=True)
class GetEdgeQuery:
    """Edge lookup by canonical edge id, current head or one historical
    revision (ADR-024 §9, §10.D). Read-only: deliberately carries no
    ``PrincipalRef``."""

    scope: GraphQueryScope
    edge_id: str

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        self.scope.validate()
        _validate_label(self.edge_id, field="edge_id")


@dataclass(frozen=True, slots=True)
class ListEdgesQuery:
    """List/filter edges by type, storage direction, and/or valid-at moment
    (ADR-024 §10.E, §10.J). No edge-property matching beyond ``edge_type``
    filtering is exposed (ADR-024 §5) — ``direction`` reuses the existing
    domain ``EdgeDirection`` (directed/undirected) semantics unchanged.
    Read-only: deliberately carries no ``PrincipalRef``."""

    scope: GraphQueryScope
    edge_type: str | None = None
    direction: EdgeDirection | None = None
    valid_at: datetime | None = None
    limit: int = MAX_QUERY_PAGE_SIZE
    before_edge_id: str | None = None

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        self.scope.validate()
        if self.edge_type is not None:
            _validate_label(self.edge_type, field="edge_type")
        if self.direction is not None and not isinstance(self.direction, EdgeDirection):
            raise InvalidQueryError("direction must be an EdgeDirection")
        if self.valid_at is not None:
            _validate_valid_at(self.valid_at)
        _validate_limit(self.limit)
        if self.before_edge_id is not None:
            _validate_label(self.before_edge_id, field="before_edge_id")


@dataclass(frozen=True, slots=True)
class ListNeighborsQuery:
    """Neighbors of one node, traversed outgoing/incoming/both directions,
    optionally filtered to those valid at a moment (ADR-024 §10.F/G/H,
    §10.J). Read-only: deliberately carries no ``PrincipalRef``."""

    scope: GraphQueryScope
    node_id: str
    direction: NeighborDirection
    valid_at: datetime | None = None
    limit: int = MAX_QUERY_PAGE_SIZE
    before_edge_id: str | None = None

    def validate(self) -> None:
        """Validate application-query invariants without opening a transaction."""
        self.scope.validate()
        _validate_label(self.node_id, field="node_id")
        if not isinstance(self.direction, NeighborDirection):
            raise InvalidQueryError("direction must be a NeighborDirection")
        if self.valid_at is not None:
            _validate_valid_at(self.valid_at)
        _validate_limit(self.limit)
        if self.before_edge_id is not None:
            _validate_label(self.before_edge_id, field="before_edge_id")


@dataclass(frozen=True, slots=True)
class ShortestPathQuery:
    """A single unweighted shortest path between two node ids, bounded by
    ``MAX_TRAVERSAL_DEPTH`` (ADR-024 §10.I, §15). No all-path, k-shortest, or
    weighted-path option is exposed. Read-only: deliberately carries no
    ``PrincipalRef``."""

    scope: GraphQueryScope
    from_node_id: str
    to_node_id: str
    maximum_depth: int = MAX_TRAVERSAL_DEPTH

    def validate(self) -> None:
        """Validate application-query invariants — including the requested
        depth ceiling — before any graph snapshot is acquired (ADR-024 §15)."""
        self.scope.validate()
        _validate_label(self.from_node_id, field="from_node_id")
        _validate_label(self.to_node_id, field="to_node_id")
        if isinstance(self.maximum_depth, bool) or not isinstance(self.maximum_depth, int):
            raise InvalidQueryError("maximum_depth must be an int")
        if self.maximum_depth < 1:
            raise InvalidQueryError(f"maximum_depth must be >= 1: {self.maximum_depth!r}")
        if self.maximum_depth > MAX_TRAVERSAL_DEPTH:
            raise PathDepthExceededError(
                f"maximum_depth must be <= {MAX_TRAVERSAL_DEPTH}: {self.maximum_depth!r}"
            )


@dataclass(frozen=True, slots=True)
class EntityAttributeHistoryQuery:
    """The value of one of a node's tracked attributes at a moment in time
    (ADR-024 §10.J, §11, §13) — the domain temporal axis, composed with
    whichever revision ``scope`` selects. Read-only: deliberately carries no
    ``PrincipalRef``."""

    scope: GraphQueryScope
    node_id: str
    attribute: str
    valid_at: datetime

    def validate(self) -> None:
        """Validate application-query invariants, rejecting a timezone-naive
        ``valid_at`` before any store interaction (ADR-024 §13)."""
        self.scope.validate()
        _validate_label(self.node_id, field="node_id")
        _validate_label(self.attribute, field="attribute")
        _validate_valid_at(self.valid_at)
