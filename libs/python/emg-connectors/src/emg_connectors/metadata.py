"""Connector metadata + descriptor (FEAT-13-1).

`ConnectorMetadata` is descriptive envelope information (description, tags,
contact). `ConnectorDescriptor` is the **central static declaration** every
connector exposes: a unique id, name, version, vendor, its capabilities (which
include supported entity types, synchronization modes, and authentication
mechanisms), and its configuration schema. It is pure, immutable data — no
vendor logic, no I/O.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from .capabilities import ConnectorCapabilities
from .configuration import ConnectorConfigurationSchema
from .enums import AuthenticationMechanism, ConnectorCapability, SynchronizationMode
from .labels import SafeLabel, SafeText
from .limits import MAX_TAGS
from .version import Version


class ConnectorMetadata(BaseModel):
    """Descriptive, immutable metadata for a connector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    description: SafeText | None = None
    tags: tuple[SafeLabel, ...] = ()
    contact: SafeLabel | None = None

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) > MAX_TAGS:
            raise ValueError(f"too many tags (max {MAX_TAGS})")
        return tuple(sorted(set(v)))


class ConnectorDescriptor(BaseModel):
    """The central, immutable static declaration a connector exposes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: SafeLabel
    name: SafeLabel
    version: Version
    vendor: SafeLabel
    capabilities: ConnectorCapabilities
    configuration_schema: ConnectorConfigurationSchema = ConnectorConfigurationSchema()
    metadata: ConnectorMetadata = ConnectorMetadata()

    def supports(self, capability: ConnectorCapability) -> bool:
        return self.capabilities.supports(capability)

    def supports_extension(self, capability: str) -> bool:
        return self.capabilities.supports_extension(capability)

    def supports_entity_type(self, entity_type: str) -> bool:
        return self.capabilities.supports_entity_type(entity_type)

    def supports_sync_mode(self, mode: SynchronizationMode) -> bool:
        return self.capabilities.supports_sync_mode(mode)

    def supports_auth(self, mechanism: AuthenticationMechanism) -> bool:
        return self.capabilities.supports_auth(mechanism)
