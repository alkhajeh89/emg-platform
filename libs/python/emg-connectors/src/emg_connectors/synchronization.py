"""Synchronization contracts (FEAT-13-1).

These model *what synchronization a connector supports and how it is requested* —
they are declarations and value objects, not an execution engine. The framework
runs no sync, opens no connection, and schedules nothing (a `schedule_hint` is
inert descriptive text, never executed).

`SynchronizationContract` declares a connector's supported modes/features;
`SynchronizationPolicy` is an immutable configuration for a sync; and
`FullSynchronization` / `IncrementalSynchronization` are immutable *plans*
(requests) describing one sync intent — a full scope, or an incremental step from
an opaque cursor.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import SynchronizationMode
from .labels import SafeLabel, SafeText
from .limits import MAX_BATCH_SIZE, MIN_BATCH_SIZE


class SynchronizationContract(BaseModel):
    """A connector's immutable declaration of the synchronization it supports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    supported_modes: tuple[SynchronizationMode, ...] = (SynchronizationMode.FULL,)
    supports_change_detection: bool = False
    supports_delete_detection: bool = False
    supports_cursor: bool = False

    @model_validator(mode="after")
    def _validate(self) -> SynchronizationContract:
        if len(self.supported_modes) == 0:
            raise ValueError("a synchronization contract must support at least one mode")
        if SynchronizationMode.INCREMENTAL in self.supported_modes and not self.supports_cursor:
            raise ValueError("incremental synchronization requires cursor support")
        return self

    def supports(self, mode: SynchronizationMode) -> bool:
        return mode in self.supported_modes


class SynchronizationPolicy(BaseModel):
    """Immutable configuration for a synchronization. `schedule_hint` is inert
    descriptive text (never executed — the framework has no scheduler)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: SynchronizationMode
    batch_size: int = Field(default=1000, ge=MIN_BATCH_SIZE, le=MAX_BATCH_SIZE)
    allow_deletes: bool = False
    schedule_hint: SafeText | None = None


class FullSynchronization(BaseModel):
    """An immutable full-synchronization *plan* (request): re-enumerate the whole
    source under a policy whose mode must be FULL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: SafeLabel
    policy: SynchronizationPolicy

    @model_validator(mode="after")
    def _validate(self) -> FullSynchronization:
        if self.policy.mode is not SynchronizationMode.FULL:
            raise ValueError("FullSynchronization requires a policy with mode=full")
        return self


class IncrementalSynchronization(BaseModel):
    """An immutable incremental-synchronization *plan* (request): enumerate changes
    since an opaque `since_cursor` under a policy whose mode must be INCREMENTAL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: SafeLabel
    policy: SynchronizationPolicy
    since_cursor: SafeLabel | None = None

    @model_validator(mode="after")
    def _validate(self) -> IncrementalSynchronization:
        if self.policy.mode is not SynchronizationMode.INCREMENTAL:
            raise ValueError("IncrementalSynchronization requires a policy with mode=incremental")
        return self
