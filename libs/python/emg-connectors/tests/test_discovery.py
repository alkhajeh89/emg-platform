"""Connector discovery over the registry (FEAT-13-1)."""

from __future__ import annotations

from emg_connectors import (
    AuthenticationMechanism,
    CapabilityRequirement,
    ConnectorCapabilities,
    ConnectorCapability,
    ConnectorDescriptor,
    ConnectorDiscovery,
    ConnectorRegistry,
    SynchronizationMode,
    Version,
)


def _reg() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.register(
        ConnectorDescriptor(
            connector_id="reader",
            name="Reader",
            version=Version(major=1, minor=0, patch=0),
            vendor="acme",
            capabilities=ConnectorCapabilities(
                capabilities=(ConnectorCapability.READ, ConnectorCapability.FULL_SYNC),
                supported_entity_types=("Person",),
                supported_sync_modes=(SynchronizationMode.FULL,),
                supported_auth_mechanisms=(AuthenticationMechanism.API_KEY,),
            ),
        )
    )
    reg.register(
        ConnectorDescriptor(
            connector_id="writer",
            name="Writer",
            version=Version(major=1, minor=0, patch=0),
            vendor="globex",
            capabilities=ConnectorCapabilities(
                capabilities=(ConnectorCapability.WRITE, ConnectorCapability.INCREMENTAL_SYNC),
                supported_entity_types=("Organization",),
                supported_sync_modes=(SynchronizationMode.INCREMENTAL,),
                supported_auth_mechanisms=(AuthenticationMechanism.OAUTH2,),
            ),
        )
    )
    return reg


def test_by_capability() -> None:
    disc = ConnectorDiscovery(_reg())
    assert [d.connector_id for d in disc.by_capability(ConnectorCapability.READ)] == ["reader"]
    assert [d.connector_id for d in disc.by_capability(ConnectorCapability.WRITE)] == ["writer"]


def test_by_entity_type_vendor_sync_auth() -> None:
    disc = ConnectorDiscovery(_reg())
    assert [d.connector_id for d in disc.by_entity_type("Person")] == ["reader"]
    assert [d.connector_id for d in disc.by_vendor("globex")] == ["writer"]
    assert [d.connector_id for d in disc.by_sync_mode(SynchronizationMode.INCREMENTAL)] == [
        "writer"
    ]
    assert [d.connector_id for d in disc.by_auth_mechanism(AuthenticationMechanism.API_KEY)] == [
        "reader"
    ]


def test_satisfying_requirement() -> None:
    disc = ConnectorDiscovery(_reg())
    req = CapabilityRequirement(
        required_capabilities=(ConnectorCapability.READ,),
        required_sync_mode=SynchronizationMode.FULL,
    )
    assert [d.connector_id for d in disc.satisfying(req)] == ["reader"]


def test_discovery_results_are_deterministic() -> None:
    disc = ConnectorDiscovery(_reg())
    assert disc.by_capability(ConnectorCapability.READ) == disc.by_capability(
        ConnectorCapability.READ
    )
