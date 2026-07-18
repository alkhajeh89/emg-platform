"""Connector health, statistics, and status (FEAT-13-1).

Immutable value objects a connector exposes about itself. `ConnectorHealth` is a
*declared* health level with an explicit `checked_at` (no probe is executed);
`ConnectorStatistics` is an immutable counters snapshot; `ConnectorStatus`
combines lifecycle state + health + statistics + last event into one snapshot.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import ConnectorEventType, ConnectorHealthStatus, ConnectorLifecycleState
from .labels import SafeLabel, SafeText


class ConnectorHealth(BaseModel):
    """A connector's immutable, declared health at an explicit moment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ConnectorHealthStatus = ConnectorHealthStatus.UNKNOWN
    checked_at: datetime
    detail: SafeText | None = None

    @property
    def is_healthy(self) -> bool:
        return self.status is ConnectorHealthStatus.HEALTHY


class ConnectorStatistics(BaseModel):
    """An immutable counters snapshot. All counters are non-negative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entities_seen: int = Field(default=0, ge=0)
    changes_emitted: int = Field(default=0, ge=0)
    syncs_run: int = Field(default=0, ge=0)
    snapshots_taken: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    last_sync_at: datetime | None = None
    last_snapshot_at: datetime | None = None


class ConnectorStatus(BaseModel):
    """An immutable combined status snapshot for a connector instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: SafeLabel
    lifecycle_state: ConnectorLifecycleState
    health: ConnectorHealth
    statistics: ConnectorStatistics
    last_event_type: ConnectorEventType | None = None
