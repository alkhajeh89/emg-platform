"""Connector discovery (FEAT-13-1).

`ConnectorDiscovery` answers "which registered connectors satisfy X?" over a
`ConnectorRegistry` — by capability, entity type, vendor, synchronization mode,
authentication mechanism, or a full `CapabilityRequirement` (via negotiation). It
is pure and deterministic (results are sorted by connector id); it holds no state
of its own and performs no I/O. This is the storage-independent **plugin/feature
discovery metadata** surface.
"""

from __future__ import annotations

from .capabilities import CapabilityRequirement, negotiate
from .enums import AuthenticationMechanism, ConnectorCapability, SynchronizationMode
from .metadata import ConnectorDescriptor
from .registry import ConnectorRegistry


class ConnectorDiscovery:
    """Read-only discovery queries over a connector registry."""

    def __init__(self, registry: ConnectorRegistry) -> None:
        self._registry = registry

    def _all(self) -> tuple[ConnectorDescriptor, ...]:
        return self._registry.descriptors()

    def by_capability(self, capability: ConnectorCapability) -> tuple[ConnectorDescriptor, ...]:
        return tuple(d for d in self._all() if d.supports(capability))

    def by_entity_type(self, entity_type: str) -> tuple[ConnectorDescriptor, ...]:
        return tuple(d for d in self._all() if d.supports_entity_type(entity_type))

    def by_vendor(self, vendor: str) -> tuple[ConnectorDescriptor, ...]:
        return tuple(d for d in self._all() if d.vendor == vendor)

    def by_sync_mode(self, mode: SynchronizationMode) -> tuple[ConnectorDescriptor, ...]:
        return tuple(d for d in self._all() if d.supports_sync_mode(mode))

    def by_auth_mechanism(
        self, mechanism: AuthenticationMechanism
    ) -> tuple[ConnectorDescriptor, ...]:
        return tuple(d for d in self._all() if d.supports_auth(mechanism))

    def satisfying(self, requirement: CapabilityRequirement) -> tuple[ConnectorDescriptor, ...]:
        """Descriptors whose capabilities fully satisfy `requirement` (negotiation
        succeeds)."""
        return tuple(d for d in self._all() if negotiate(d.capabilities, requirement).satisfied)
