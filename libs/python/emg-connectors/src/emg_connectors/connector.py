"""The connector contract + a framework base class (FEAT-13-1).

`Connector` is the **protocol** every connector satisfies — the contract, not an
implementation. `AbstractConnector` is a vendor-neutral framework base that a
plugin author extends: it holds the descriptor, manages the lifecycle state
machine, and exposes health/statistics/status — with **no vendor logic and no
I/O**. Timestamps are always supplied by the caller (no wall-clock), so behaviour
stays deterministic. The library ships **no real connector**; a plugin provides
the vendor behaviour.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .capabilities import ConnectorCapabilities
from .configuration import ConnectorConfigurationSchema
from .enums import ConnectorLifecycleState
from .health import ConnectorHealth, ConnectorStatistics, ConnectorStatus
from .lifecycle import ConnectorLifecycle
from .metadata import ConnectorDescriptor


@runtime_checkable
class Connector(Protocol):
    """The contract every connector satisfies. Implemented by plugins, never by
    the framework."""

    def descriptor(self) -> ConnectorDescriptor: ...

    def capabilities(self) -> ConnectorCapabilities: ...

    def configuration_schema(self) -> ConnectorConfigurationSchema: ...

    def health(self) -> ConnectorHealth: ...

    def statistics(self) -> ConnectorStatistics: ...

    def status(self) -> ConnectorStatus: ...

    @property
    def lifecycle_state(self) -> ConnectorLifecycleState: ...


class AbstractConnector:
    """A vendor-neutral framework base a plugin extends. Manages the lifecycle
    state machine and health/statistics snapshots; contains no vendor logic and
    performs no I/O. Not a real connector — a plugin supplies actual behaviour."""

    def __init__(
        self,
        descriptor: ConnectorDescriptor,
        created_at: datetime,
        *,
        state: ConnectorLifecycleState = ConnectorLifecycleState.REGISTERED,
    ) -> None:
        self._descriptor = descriptor
        self._state = state
        self._health = ConnectorHealth(checked_at=created_at)
        self._statistics = ConnectorStatistics()

    # --- contract surface ---
    def descriptor(self) -> ConnectorDescriptor:
        return self._descriptor

    def capabilities(self) -> ConnectorCapabilities:
        return self._descriptor.capabilities

    def configuration_schema(self) -> ConnectorConfigurationSchema:
        return self._descriptor.configuration_schema

    def health(self) -> ConnectorHealth:
        return self._health

    def statistics(self) -> ConnectorStatistics:
        return self._statistics

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            connector_id=self._descriptor.connector_id,
            lifecycle_state=self._state,
            health=self._health,
            statistics=self._statistics,
        )

    @property
    def lifecycle_state(self) -> ConnectorLifecycleState:
        return self._state

    # --- state management (no I/O) ---
    def transition(self, to_state: ConnectorLifecycleState) -> None:
        """Move to `to_state` if the lifecycle state machine permits it; otherwise
        raise `ConnectorLifecycleError`."""
        ConnectorLifecycle.assert_transition(self._state, to_state)
        self._state = to_state

    def report_health(self, health: ConnectorHealth) -> None:
        self._health = health

    def report_statistics(self, statistics: ConnectorStatistics) -> None:
        self._statistics = statistics
