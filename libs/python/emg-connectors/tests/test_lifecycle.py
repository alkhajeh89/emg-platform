"""Connector + plugin lifecycle state machines (FEAT-13-1)."""

from __future__ import annotations

import pytest
from emg_connectors import (
    ConnectorLifecycle,
    ConnectorLifecycleError,
    ConnectorLifecycleState,
    PluginLifecycle,
    PluginLifecycleState,
)

CS = ConnectorLifecycleState
PS = PluginLifecycleState

_CONNECTOR_LEGAL = {
    (CS.REGISTERED, CS.CONFIGURED),
    (CS.CONFIGURED, CS.VALIDATED),
    (CS.VALIDATED, CS.ACTIVE),
    (CS.VALIDATED, CS.CONFIGURED),
    (CS.ACTIVE, CS.PAUSED),
    (CS.ACTIVE, CS.STOPPED),
    (CS.ACTIVE, CS.FAILED),
    (CS.PAUSED, CS.ACTIVE),
    (CS.PAUSED, CS.STOPPED),
    (CS.STOPPED, CS.ACTIVE),
    (CS.STOPPED, CS.RETIRED),
    (CS.FAILED, CS.STOPPED),
    (CS.FAILED, CS.RETIRED),
}

_PLUGIN_LEGAL = {
    (PS.DISCOVERED, PS.VALIDATED),
    (PS.VALIDATED, PS.REGISTERED),
    (PS.REGISTERED, PS.ENABLED),
    (PS.REGISTERED, PS.DISABLED),
    (PS.ENABLED, PS.DISABLED),
    (PS.ENABLED, PS.RETIRED),
    (PS.DISABLED, PS.ENABLED),
    (PS.DISABLED, PS.RETIRED),
}


def test_connector_transition_table_is_golden() -> None:
    actual = {(a, b) for a in CS for b in CS if ConnectorLifecycle.is_valid_transition(a, b)}
    assert actual == _CONNECTOR_LEGAL


def test_plugin_transition_table_is_golden() -> None:
    actual = {(a, b) for a in PS for b in PS if PluginLifecycle.is_valid_transition(a, b)}
    assert actual == _PLUGIN_LEGAL


def test_no_self_transitions() -> None:
    for cs in CS:
        assert not ConnectorLifecycle.is_valid_transition(cs, cs)
    for ps in PS:
        assert not PluginLifecycle.is_valid_transition(ps, ps)


def test_retired_is_terminal() -> None:
    assert ConnectorLifecycle.allowed_transitions(CS.RETIRED) == frozenset()
    assert PluginLifecycle.allowed_transitions(PS.RETIRED) == frozenset()


def test_assert_transition_raises_typed() -> None:
    ConnectorLifecycle.assert_transition(CS.REGISTERED, CS.CONFIGURED)  # ok
    with pytest.raises(ConnectorLifecycleError):
        ConnectorLifecycle.assert_transition(CS.ACTIVE, CS.RETIRED)
    with pytest.raises(ConnectorLifecycleError):
        PluginLifecycle.assert_transition(PS.DISCOVERED, PS.ENABLED)
