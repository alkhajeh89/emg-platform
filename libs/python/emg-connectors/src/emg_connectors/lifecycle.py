"""Connector and plugin lifecycle state machines (FEAT-13-1).

Two fixed, closed transition tables — one for a connector *instance*
(`ConnectorLifecycle`) and one for a registered plugin (`PluginLifecycle`). A
transition is either in the table or it is rejected; there is no caller-supplied
rule and no arbitrary code. Both are pure/deterministic and manage *state only* —
no side effects, no I/O.
"""

from __future__ import annotations

from .enums import ConnectorLifecycleState, PluginLifecycleState
from .errors import ConnectorLifecycleError

_CONNECTOR_TRANSITIONS: dict[ConnectorLifecycleState, frozenset[ConnectorLifecycleState]] = {
    ConnectorLifecycleState.REGISTERED: frozenset({ConnectorLifecycleState.CONFIGURED}),
    ConnectorLifecycleState.CONFIGURED: frozenset({ConnectorLifecycleState.VALIDATED}),
    ConnectorLifecycleState.VALIDATED: frozenset(
        {ConnectorLifecycleState.ACTIVE, ConnectorLifecycleState.CONFIGURED}
    ),
    ConnectorLifecycleState.ACTIVE: frozenset(
        {
            ConnectorLifecycleState.PAUSED,
            ConnectorLifecycleState.STOPPED,
            ConnectorLifecycleState.FAILED,
        }
    ),
    ConnectorLifecycleState.PAUSED: frozenset(
        {ConnectorLifecycleState.ACTIVE, ConnectorLifecycleState.STOPPED}
    ),
    ConnectorLifecycleState.STOPPED: frozenset(
        {ConnectorLifecycleState.ACTIVE, ConnectorLifecycleState.RETIRED}
    ),
    ConnectorLifecycleState.FAILED: frozenset(
        {ConnectorLifecycleState.STOPPED, ConnectorLifecycleState.RETIRED}
    ),
    ConnectorLifecycleState.RETIRED: frozenset(),
}

_PLUGIN_TRANSITIONS: dict[PluginLifecycleState, frozenset[PluginLifecycleState]] = {
    PluginLifecycleState.DISCOVERED: frozenset({PluginLifecycleState.VALIDATED}),
    PluginLifecycleState.VALIDATED: frozenset({PluginLifecycleState.REGISTERED}),
    PluginLifecycleState.REGISTERED: frozenset(
        {PluginLifecycleState.ENABLED, PluginLifecycleState.DISABLED}
    ),
    PluginLifecycleState.ENABLED: frozenset(
        {PluginLifecycleState.DISABLED, PluginLifecycleState.RETIRED}
    ),
    PluginLifecycleState.DISABLED: frozenset(
        {PluginLifecycleState.ENABLED, PluginLifecycleState.RETIRED}
    ),
    PluginLifecycleState.RETIRED: frozenset(),
}


class ConnectorLifecycle:
    """The connector-instance lifecycle state machine (fixed, deterministic)."""

    @staticmethod
    def is_valid_transition(
        from_state: ConnectorLifecycleState, to_state: ConnectorLifecycleState
    ) -> bool:
        return to_state in _CONNECTOR_TRANSITIONS[from_state]

    @staticmethod
    def allowed_transitions(
        from_state: ConnectorLifecycleState,
    ) -> frozenset[ConnectorLifecycleState]:
        return _CONNECTOR_TRANSITIONS[from_state]

    @staticmethod
    def assert_transition(
        from_state: ConnectorLifecycleState, to_state: ConnectorLifecycleState
    ) -> None:
        if to_state not in _CONNECTOR_TRANSITIONS[from_state]:
            raise ConnectorLifecycleError(
                f"illegal connector transition {from_state.value} -> {to_state.value}"
            )


class PluginLifecycle:
    """The plugin lifecycle state machine (fixed, deterministic)."""

    @staticmethod
    def is_valid_transition(
        from_state: PluginLifecycleState, to_state: PluginLifecycleState
    ) -> bool:
        return to_state in _PLUGIN_TRANSITIONS[from_state]

    @staticmethod
    def allowed_transitions(from_state: PluginLifecycleState) -> frozenset[PluginLifecycleState]:
        return _PLUGIN_TRANSITIONS[from_state]

    @staticmethod
    def assert_transition(from_state: PluginLifecycleState, to_state: PluginLifecycleState) -> None:
        if to_state not in _PLUGIN_TRANSITIONS[from_state]:
            raise ConnectorLifecycleError(
                f"illegal plugin transition {from_state.value} -> {to_state.value}"
            )
