"""Connector registry (FEAT-13-1).

An in-memory registry of `ConnectorDescriptor`s (optionally recording the
providing plugin id). Deterministic, bounded, storage-independent — no filesystem,
no database, no network. Registration is explicit and in-process.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .errors import ConnectorNotFoundError, ConnectorRegistrationError
from .labels import SafeLabel
from .limits import MAX_REGISTERED_CONNECTORS
from .metadata import ConnectorDescriptor


class RegisteredConnector(BaseModel):
    """An immutable registry entry: a descriptor and its optional providing plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    descriptor: ConnectorDescriptor
    plugin_id: SafeLabel | None = None


class ConnectorRegistry:
    """An in-memory, deterministic registry of connector descriptors."""

    def __init__(self) -> None:
        self._entries: dict[str, RegisteredConnector] = {}

    def register(self, descriptor: ConnectorDescriptor, *, plugin_id: str | None = None) -> None:
        """Register a connector descriptor. Raises on a duplicate id or when the
        registry is full."""
        cid = descriptor.connector_id
        if cid in self._entries:
            raise ConnectorRegistrationError(f"connector {cid!r} is already registered")
        if len(self._entries) >= MAX_REGISTERED_CONNECTORS:
            raise ConnectorRegistrationError("connector registry is full")
        self._entries[cid] = RegisteredConnector(descriptor=descriptor, plugin_id=plugin_id)

    def unregister(self, connector_id: str) -> None:
        if connector_id not in self._entries:
            raise ConnectorNotFoundError(f"connector {connector_id!r} is not registered")
        del self._entries[connector_id]

    def contains(self, connector_id: str) -> bool:
        return connector_id in self._entries

    def get(self, connector_id: str) -> ConnectorDescriptor:
        if connector_id not in self._entries:
            raise ConnectorNotFoundError(f"connector {connector_id!r} is not registered")
        return self._entries[connector_id].descriptor

    def entry(self, connector_id: str) -> RegisteredConnector:
        if connector_id not in self._entries:
            raise ConnectorNotFoundError(f"connector {connector_id!r} is not registered")
        return self._entries[connector_id]

    def connector_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def descriptors(self) -> tuple[ConnectorDescriptor, ...]:
        return tuple(self._entries[cid].descriptor for cid in sorted(self._entries))

    def count(self) -> int:
        return len(self._entries)
