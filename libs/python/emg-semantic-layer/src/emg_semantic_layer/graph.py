"""Storage-independent graph value objects (FEAT-05-4).

`SemanticNode`, `SemanticRelationship`, and `SemanticGraph` are **immutable value
objects**, not a database. They model a *materialised* piece of knowledge graph —
the shape a query result takes, or a hand-built fixture — decoupled from any
persistence technology. There is no store, no driver, no I/O here: a `SemanticGraph`
is an in-memory, frozen snapshot with pure lookup helpers.

Immutability is **deep**: the models are frozen (no field reassignment) *and*
`properties` is stored as a read-only mapping over a private copy, so a caller
can neither mutate a returned node's properties nor mutate the dictionary it
passed in after construction. `SemanticGraph` exposes nodes/relationships as
tuples, so its contents cannot be mutated through the graph either.

Node/relationship *types* are plain string labels and properties are plain scalar
data, so this layer neither depends on nor re-implements Module 7's ontology
(`emg-ontology`) — a storage binding is responsible for mapping ontology entities
onto these projections. All identifiers/labels and property keys are validated by
`ensure_safe_label` (no control/bidi characters). `classification` reuses the
platform-wide `emg_common_types.Classification` vocabulary so that a future
consumer can apply need-to-know filtering (Module 7 §21) against a stable label
set.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from emg_common_types import Classification
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from .validation import SafeLabel, ensure_safe_label

# A property value is a JSON-style scalar only: no nested objects, no callables,
# no arbitrary Python objects. This keeps nodes/relationships pure data and
# closes off arbitrary-object injection through properties.
PropertyValue = str | int | float | bool | None


def _empty_properties() -> Mapping[str, PropertyValue]:
    # A fresh read-only empty mapping per instance (used as the field default via
    # default_factory; a static MappingProxyType default cannot be deep-copied).
    return MappingProxyType({})


def _freeze_properties(value: Mapping[str, PropertyValue]) -> Mapping[str, PropertyValue]:
    # Validate keys (same rule as labels), sort for deterministic serialisation,
    # copy into a fresh dict (defeats input-dict aliasing), and wrap read-only so
    # the mapping cannot be mutated through the model afterward.
    for key in value:
        if not isinstance(key, str):  # pragma: no cover - defensive
            raise ValueError("property keys must be strings")
        ensure_safe_label(key)
    return MappingProxyType({k: value[k] for k in sorted(value)})


class SemanticNode(BaseModel):
    """An immutable node projection: a stable id, a type label, an optional
    classification, and scalar properties. Properties are a read-only mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: SafeLabel
    type: SafeLabel
    classification: Classification | None = None
    properties: Mapping[str, PropertyValue] = Field(default_factory=_empty_properties)

    _freeze = field_validator("properties")(staticmethod(_freeze_properties))

    @field_serializer("properties")
    def _serialize_properties(self, value: Mapping[str, PropertyValue]) -> dict[str, PropertyValue]:
        return dict(value)


class SemanticRelationship(BaseModel):
    """An immutable directed relationship projection between two node ids."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_id: SafeLabel
    type: SafeLabel
    source_id: SafeLabel
    target_id: SafeLabel
    properties: Mapping[str, PropertyValue] = Field(default_factory=_empty_properties)

    _freeze = field_validator("properties")(staticmethod(_freeze_properties))

    @field_serializer("properties")
    def _serialize_properties(self, value: Mapping[str, PropertyValue]) -> dict[str, PropertyValue]:
        return dict(value)


class SemanticGraph(BaseModel):
    """An immutable, storage-independent snapshot of nodes + relationships with
    pure lookup helpers. Not a persistence engine — just a frozen value object.
    Nodes and relationships are held as tuples, so the graph's contents cannot be
    mutated through it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[SemanticNode, ...] = ()
    relationships: tuple[SemanticRelationship, ...] = ()

    @field_validator("nodes")
    @classmethod
    def _unique_node_ids(cls, value: tuple[SemanticNode, ...]) -> tuple[SemanticNode, ...]:
        ids = [n.node_id for n in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate node_id in SemanticGraph")
        return value

    @field_validator("relationships")
    @classmethod
    def _unique_relationship_ids(
        cls, value: tuple[SemanticRelationship, ...]
    ) -> tuple[SemanticRelationship, ...]:
        ids = [r.relationship_id for r in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate relationship_id in SemanticGraph")
        return value

    def node(self, node_id: str) -> SemanticNode | None:
        """Return the node with this id, or None. Pure, no I/O."""
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    def relationships_of(self, node_id: str) -> tuple[SemanticRelationship, ...]:
        """Every relationship incident to `node_id` (as source or target)."""
        return tuple(
            r for r in self.relationships if r.source_id == node_id or r.target_id == node_id
        )

    def neighbors(self, node_id: str) -> tuple[SemanticNode, ...]:
        """The distinct nodes directly connected to `node_id`, in stable order."""
        seen: list[str] = []
        for r in self.relationships:
            if r.source_id == node_id and r.target_id not in seen:
                seen.append(r.target_id)
            elif r.target_id == node_id and r.source_id not in seen:
                seen.append(r.source_id)
        out: list[SemanticNode] = []
        for nid in seen:
            found = self.node(nid)
            if found is not None:
                out.append(found)
        return tuple(out)
