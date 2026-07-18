"""Connector capabilities + capability negotiation + feature discovery (FEAT-13-1).

`ConnectorCapabilities` is a connector's immutable declaration of *what it
supports*: which capabilities, entity types, synchronization modes, and
authentication mechanisms. `CapabilityRequirement` is a consumer's immutable
statement of *what it needs*. `negotiate` compares the two deterministically and
returns a typed `CapabilityNegotiation` result (no exception on mismatch — a
caller decides). `CapabilityRegistry` is the canonical catalogue of known
capabilities for **feature discovery**.

Everything here is pure data + pure functions. No vendor branching: the framework
compares declared sets; it never asks "is this SAP?".
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import AuthenticationMechanism, ConnectorCapability, SynchronizationMode
from .labels import SafeLabel
from .limits import (
    MAX_AUTH_MECHANISMS,
    MAX_CAPABILITIES,
    MAX_ENTITY_TYPES,
    MAX_EXTENSION_CAPABILITIES,
    MAX_SYNC_MODES,
)

# The reserved values a vendor extension capability may never reuse (the standard
# capability vocabulary). Keeps the two namespaces unambiguous.
_STANDARD_CAPABILITY_VALUES: frozenset[str] = frozenset(c.value for c in ConnectorCapability)


def _unique_sorted(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


class ConnectorCapabilities(BaseModel):
    """A connector's immutable declaration of supported capabilities, entity
    types, synchronization modes, and authentication mechanisms. Collections are
    normalised to sorted-unique tuples for deterministic equality/serialisation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capabilities: tuple[ConnectorCapability, ...] = ()
    # Vendor-specific capabilities a connector declares beyond the standard,
    # strongly-typed `ConnectorCapability` set — free-form (but safe-label
    # validated) strings so a new connector can advertise a capability the core
    # does not enumerate, WITHOUT editing the framework. Convention: namespace them
    # (e.g. "acme:incremental_delta"). A standard capability value may not be
    # reused here.
    extension_capabilities: tuple[SafeLabel, ...] = ()
    supported_entity_types: tuple[SafeLabel, ...] = ()
    supported_sync_modes: tuple[SynchronizationMode, ...] = ()
    supported_auth_mechanisms: tuple[AuthenticationMechanism, ...] = (AuthenticationMechanism.NONE,)

    @field_validator("capabilities")
    @classmethod
    def _norm_caps(cls, v: tuple[ConnectorCapability, ...]) -> tuple[ConnectorCapability, ...]:
        if len(v) > MAX_CAPABILITIES:
            raise ValueError(f"too many capabilities (max {MAX_CAPABILITIES})")
        return tuple(sorted(set(v), key=lambda c: c.value))

    @field_validator("extension_capabilities")
    @classmethod
    def _norm_ext_caps(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) > MAX_EXTENSION_CAPABILITIES:
            raise ValueError(f"too many extension capabilities (max {MAX_EXTENSION_CAPABILITIES})")
        clashing = sorted(x for x in v if x in _STANDARD_CAPABILITY_VALUES)
        if clashing:
            raise ValueError(
                f"extension capabilities must not reuse a standard capability value: {clashing}"
            )
        return _unique_sorted(v)

    @field_validator("supported_entity_types")
    @classmethod
    def _norm_entity_types(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) > MAX_ENTITY_TYPES:
            raise ValueError(f"too many entity types (max {MAX_ENTITY_TYPES})")
        return _unique_sorted(v)

    @field_validator("supported_sync_modes")
    @classmethod
    def _norm_sync(cls, v: tuple[SynchronizationMode, ...]) -> tuple[SynchronizationMode, ...]:
        if len(v) > MAX_SYNC_MODES:
            raise ValueError(f"too many sync modes (max {MAX_SYNC_MODES})")
        return tuple(sorted(set(v), key=lambda m: m.value))

    @field_validator("supported_auth_mechanisms")
    @classmethod
    def _norm_auth(
        cls, v: tuple[AuthenticationMechanism, ...]
    ) -> tuple[AuthenticationMechanism, ...]:
        if len(v) == 0:
            raise ValueError("at least one authentication mechanism must be declared")
        if len(v) > MAX_AUTH_MECHANISMS:
            raise ValueError(f"too many auth mechanisms (max {MAX_AUTH_MECHANISMS})")
        return tuple(sorted(set(v), key=lambda a: a.value))

    def supports(self, capability: ConnectorCapability) -> bool:
        return capability in self.capabilities

    def supports_extension(self, capability: str) -> bool:
        """True iff the connector declares this vendor-specific extension
        capability (a free-form, non-standard capability name)."""
        return capability in self.extension_capabilities

    def supports_entity_type(self, entity_type: str) -> bool:
        return entity_type in self.supported_entity_types

    def supports_sync_mode(self, mode: SynchronizationMode) -> bool:
        return mode in self.supported_sync_modes

    def supports_auth(self, mechanism: AuthenticationMechanism) -> bool:
        return mechanism in self.supported_auth_mechanisms


class CapabilityRequirement(BaseModel):
    """A consumer's immutable statement of what a connector must support."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required_capabilities: tuple[ConnectorCapability, ...] = ()
    required_extension_capabilities: tuple[SafeLabel, ...] = ()
    required_entity_types: tuple[SafeLabel, ...] = ()
    required_sync_mode: SynchronizationMode | None = None
    required_auth_mechanism: AuthenticationMechanism | None = None


class CapabilityNegotiation(BaseModel):
    """The immutable, deterministic result of negotiating a requirement against a
    connector's declared capabilities. `satisfied` iff nothing is missing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    satisfied: bool
    missing_capabilities: tuple[ConnectorCapability, ...] = ()
    missing_extension_capabilities: tuple[str, ...] = ()
    missing_entity_types: tuple[str, ...] = ()
    missing_sync_mode: SynchronizationMode | None = None
    missing_auth_mechanism: AuthenticationMechanism | None = None


def negotiate(
    available: ConnectorCapabilities, required: CapabilityRequirement
) -> CapabilityNegotiation:
    """Compare `required` against `available`; return a typed result. Pure and
    deterministic (missing collections are sorted)."""
    missing_caps = tuple(
        sorted(
            (c for c in required.required_capabilities if not available.supports(c)),
            key=lambda c: c.value,
        )
    )
    missing_ext = tuple(
        sorted(
            x
            for x in required.required_extension_capabilities
            if not available.supports_extension(x)
        )
    )
    missing_types = tuple(
        sorted(t for t in required.required_entity_types if not available.supports_entity_type(t))
    )
    missing_sync = (
        required.required_sync_mode
        if required.required_sync_mode is not None
        and not available.supports_sync_mode(required.required_sync_mode)
        else None
    )
    missing_auth = (
        required.required_auth_mechanism
        if required.required_auth_mechanism is not None
        and not available.supports_auth(required.required_auth_mechanism)
        else None
    )
    satisfied = (
        not missing_caps
        and not missing_ext
        and not missing_types
        and missing_sync is None
        and missing_auth is None
    )
    return CapabilityNegotiation(
        satisfied=satisfied,
        missing_capabilities=missing_caps,
        missing_extension_capabilities=missing_ext,
        missing_entity_types=missing_types,
        missing_sync_mode=missing_sync,
        missing_auth_mechanism=missing_auth,
    )


class FeatureDescriptor(BaseModel):
    """A catalogued capability + human-readable description (feature discovery)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: ConnectorCapability
    description: str


class CapabilityRegistry(BaseModel):
    """The canonical catalogue of framework-known capabilities, for feature
    discovery and negotiation. Immutable; the default instance lists every
    `ConnectorCapability`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    features: tuple[FeatureDescriptor, ...] = Field(default_factory=tuple)

    def is_known(self, capability: ConnectorCapability) -> bool:
        return any(f.capability is capability for f in self.features)

    def known_capabilities(self) -> tuple[ConnectorCapability, ...]:
        return tuple(f.capability for f in self.features)

    def describe(self, capability: ConnectorCapability) -> str | None:
        for f in self.features:
            if f.capability is capability:
                return f.description
        return None


_FEATURE_DESCRIPTIONS: dict[ConnectorCapability, str] = {
    ConnectorCapability.READ: "read source records",
    ConnectorCapability.WRITE: "write records back to the source",
    ConnectorCapability.FULL_SYNC: "enumerate the full source dataset",
    ConnectorCapability.INCREMENTAL_SYNC: "enumerate changes since a cursor",
    ConnectorCapability.CHANGE_DETECTION: "detect created/updated records",
    ConnectorCapability.DELETE_DETECTION: "detect deleted records",
    ConnectorCapability.SCHEMA_DISCOVERY: "describe the source schema",
    ConnectorCapability.ENTITY_MAPPING: "map source records to entities",
    ConnectorCapability.RELATIONSHIP_MAPPING: "map source links to relationships",
    ConnectorCapability.METADATA_MAPPING: "map source metadata",
    ConnectorCapability.SNAPSHOTTING: "produce point-in-time snapshots",
    ConnectorCapability.HEALTH_CHECK: "report health",
    ConnectorCapability.STATISTICS: "report operational statistics",
}

DEFAULT_CAPABILITY_REGISTRY = CapabilityRegistry(
    features=tuple(
        FeatureDescriptor(capability=c, description=_FEATURE_DESCRIPTIONS[c])
        for c in ConnectorCapability
    )
)
