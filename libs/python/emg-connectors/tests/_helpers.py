"""Shared test doubles + factories for emg-connectors (FEAT-13-1).

Test-only neutral fakes (no vendor, no I/O) used to exercise the framework's
contracts. The library itself ships no connector. Imported by `conftest.py` (which
puts this directory on `sys.path`) and by the test modules.
"""

from __future__ import annotations

from datetime import datetime, timezone

from emg_connectors import (
    AbstractConnector,
    AuthenticationMechanism,
    ConnectorCapabilities,
    ConnectorCapability,
    ConnectorContext,
    ConnectorDescriptor,
    ConnectorPluginDescriptor,
    SynchronizationMode,
    Version,
    VersionRange,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_capabilities() -> ConnectorCapabilities:
    return ConnectorCapabilities(
        capabilities=(
            ConnectorCapability.READ,
            ConnectorCapability.FULL_SYNC,
            ConnectorCapability.INCREMENTAL_SYNC,
            ConnectorCapability.CHANGE_DETECTION,
        ),
        supported_entity_types=("Person", "Organization"),
        supported_sync_modes=(SynchronizationMode.FULL, SynchronizationMode.INCREMENTAL),
        supported_auth_mechanisms=(AuthenticationMechanism.API_KEY,),
    )


def make_descriptor(connector_id: str = "acme-dir") -> ConnectorDescriptor:
    return ConnectorDescriptor(
        connector_id=connector_id,
        name="Acme Directory",
        version=Version(major=1, minor=2, patch=0),
        vendor="acme",
        capabilities=make_capabilities(),
    )


class FakeConnector(AbstractConnector):
    """A neutral test connector (no vendor logic)."""


class FakePlugin:
    """A neutral test plugin providing one connector. Not a real integration."""

    def __init__(
        self, connector_id: str = "acme-dir", framework_min: tuple[int, int, int] = (1, 0, 0)
    ) -> None:
        self._descriptor = make_descriptor(connector_id)
        self._plugin_descriptor = ConnectorPluginDescriptor(
            plugin_id="acme",
            name="Acme Plugin",
            version=Version(major=1, minor=0, patch=0),
            vendor="acme",
            framework_compatibility=VersionRange(
                minimum=Version(
                    major=framework_min[0], minor=framework_min[1], patch=framework_min[2]
                )
            ),
            provided_connectors=(self._descriptor,),
        )

    def plugin_descriptor(self) -> ConnectorPluginDescriptor:
        return self._plugin_descriptor

    def create_connector(self, connector_id: str, context: ConnectorContext) -> FakeConnector:
        descriptor = self._plugin_descriptor.connector(connector_id)
        assert descriptor is not None
        return FakeConnector(descriptor, created_at=context.as_of)
