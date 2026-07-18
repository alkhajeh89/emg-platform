"""Mapping contracts (FEAT-13-1).

A connector reads a vendor's `SourceRecord` (a neutral, scalar bag of fields) and
maps it onto neutral `MappedEntity` / `MappedRelationship` / `MappedMetadata`
value objects. The mapper **protocols** define this contract; the framework ships
no implementation and imports no ontology (the mapped types are deliberately
neutral — a downstream binding maps them onto the Module 7 ontology). This keeps
the framework storage- and vendor-independent.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from .configuration import ScalarValue
from .labels import SafeLabel, ensure_safe_label


def _freeze(v: Mapping[str, ScalarValue]) -> Mapping[str, ScalarValue]:
    for key in v:
        if not isinstance(key, str):  # pragma: no cover - defensive
            raise ValueError("keys must be strings")
        ensure_safe_label(key)
    return MappingProxyType({k: v[k] for k in sorted(v)})


class SourceRecord(BaseModel):
    """An immutable, vendor-neutral input record a connector reads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_type: SafeLabel
    external_id: SafeLabel
    attributes: Mapping[str, ScalarValue] = Field(default_factory=dict)

    _fa = field_validator("attributes")(staticmethod(_freeze))

    @field_serializer("attributes")
    def _ser(self, v: Mapping[str, ScalarValue]) -> dict[str, ScalarValue]:
        return dict(v)


class MappedEntity(BaseModel):
    """A neutral mapped entity (no ontology dependency)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: SafeLabel
    external_id: SafeLabel
    classification: SafeLabel | None = None
    attributes: Mapping[str, ScalarValue] = Field(default_factory=dict)

    _fa = field_validator("attributes")(staticmethod(_freeze))

    @field_serializer("attributes")
    def _ser(self, v: Mapping[str, ScalarValue]) -> dict[str, ScalarValue]:
        return dict(v)


class MappedRelationship(BaseModel):
    """A neutral mapped relationship between two external ids."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_type: SafeLabel
    source_external_id: SafeLabel
    target_external_id: SafeLabel
    attributes: Mapping[str, ScalarValue] = Field(default_factory=dict)

    _fa = field_validator("attributes")(staticmethod(_freeze))

    @field_serializer("attributes")
    def _ser(self, v: Mapping[str, ScalarValue]) -> dict[str, ScalarValue]:
        return dict(v)


class MappedMetadata(BaseModel):
    """Neutral mapped metadata for a source record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_id: SafeLabel
    values: Mapping[str, ScalarValue] = Field(default_factory=dict)

    _fv = field_validator("values")(staticmethod(_freeze))

    @field_serializer("values")
    def _ser(self, v: Mapping[str, ScalarValue]) -> dict[str, ScalarValue]:
        return dict(v)


@runtime_checkable
class ConnectorMapper(Protocol):
    """Marker base protocol for all connector mappers."""

    def source_record_type(self) -> str:
        """The `record_type` this mapper accepts."""
        ...


@runtime_checkable
class EntityMapper(Protocol):
    """Maps a source record to a neutral entity. Implemented by a plugin, never by
    the framework."""

    def map_entity(self, record: SourceRecord) -> MappedEntity: ...


@runtime_checkable
class RelationshipMapper(Protocol):
    """Maps a source record to zero or more neutral relationships."""

    def map_relationships(self, record: SourceRecord) -> tuple[MappedRelationship, ...]: ...


@runtime_checkable
class MetadataMapper(Protocol):
    """Maps a source record to neutral metadata."""

    def map_metadata(self, record: SourceRecord) -> MappedMetadata: ...
