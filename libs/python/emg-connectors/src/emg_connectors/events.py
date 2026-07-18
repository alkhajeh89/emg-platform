"""Connector events, changes, and snapshots (FEAT-13-1).

Immutable value objects describing *what a connector reports*, as contracts:
`ConnectorEvent` (a lifecycle/operational event), `ConnectorChange` (a detected
change — the change-data-capture contract), and `ConnectorSnapshot` (a
point-in-time marker with an opaque cursor/watermark). The framework emits none of
these itself; they are the shapes a connector or a future sync engine produces.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from .configuration import ScalarValue
from .enums import ChangeType, ConnectorEventType, SynchronizationMode
from .labels import SafeLabel, SafeText, ensure_safe_label


class ConnectorEvent(BaseModel):
    """An immutable record of one connector lifecycle/operational event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: ConnectorEventType
    connector_id: SafeLabel
    occurred_at: datetime
    correlation_id: SafeLabel | None = None
    detail: SafeText | None = None


class ConnectorChange(BaseModel):
    """An immutable change-data-capture record: one create/update/delete of one
    source record, identified by its (opaque) external id and entity type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    change_type: ChangeType
    entity_type: SafeLabel
    external_id: SafeLabel
    occurred_at: datetime
    attributes: Mapping[str, ScalarValue] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def _freeze_attrs(cls, v: Mapping[str, ScalarValue]) -> Mapping[str, ScalarValue]:
        for key in v:
            if not isinstance(key, str):  # pragma: no cover - defensive
                raise ValueError("attribute keys must be strings")
            ensure_safe_label(key)
        return MappingProxyType({k: v[k] for k in sorted(v)})

    @field_serializer("attributes")
    def _ser_attrs(self, v: Mapping[str, ScalarValue]) -> dict[str, ScalarValue]:
        return dict(v)


class ConnectorSnapshot(BaseModel):
    """An immutable point-in-time snapshot marker: an opaque cursor/watermark and
    the entity count observed, for full/incremental synchronization bookkeeping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: SafeLabel
    connector_id: SafeLabel
    taken_at: datetime
    mode: SynchronizationMode
    cursor: SafeLabel | None = None
    entity_count: int = Field(default=0, ge=0)
