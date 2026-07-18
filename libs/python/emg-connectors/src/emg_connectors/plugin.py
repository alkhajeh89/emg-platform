"""Plugin architecture (FEAT-13-1).

The framework is extended by **plugins**, added independently without modifying the
core. A `ConnectorPluginDescriptor` declares a plugin's identity, the framework
version range it supports, and the connector descriptors it provides. The
`ConnectorPlugin` protocol is the extension unit (it can create connectors).
`PluginValidation` and `PluginCompatibility` are pure checks. `ConnectorPluginLoader`
is the **in-memory** registration model — it validates, checks compatibility, and
registers plugins and their connectors.

Explicitly out of scope this sprint (and intentionally not implemented): dynamic
filesystem scanning, Python entry-point loading, package installation, remote
plugin marketplaces, and runtime code execution. Registration is in-memory only.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from .connector import Connector
from .context import ConnectorContext
from .discovery import ConnectorDiscovery
from .enums import PluginLifecycleState
from .errors import (
    ConnectorCompatibilityError,
    ConnectorNotFoundError,
    ConnectorRegistrationError,
    PluginValidationError,
)
from .labels import SafeLabel
from .lifecycle import PluginLifecycle
from .limits import MAX_PROVIDED_CONNECTORS_PER_PLUGIN, MAX_REGISTERED_PLUGINS
from .metadata import ConnectorDescriptor
from .registry import ConnectorRegistry
from .validation import connector_coherence_issues
from .version import FRAMEWORK_VERSION, Version, VersionRange


class ConnectorPluginDescriptor(BaseModel):
    """A plugin's immutable declaration: identity, the framework version range it
    is compatible with, and the connector descriptors it provides."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plugin_id: SafeLabel
    name: SafeLabel
    version: Version
    vendor: SafeLabel
    framework_compatibility: VersionRange
    provided_connectors: tuple[ConnectorDescriptor, ...]

    @model_validator(mode="after")
    def _validate(self) -> ConnectorPluginDescriptor:
        if len(self.provided_connectors) == 0:
            raise ValueError("a plugin must provide at least one connector descriptor")
        if len(self.provided_connectors) > MAX_PROVIDED_CONNECTORS_PER_PLUGIN:
            raise ValueError(
                f"a plugin provides too many connectors "
                f"(max {MAX_PROVIDED_CONNECTORS_PER_PLUGIN})"
            )
        ids = [c.connector_id for c in self.provided_connectors]
        if len(ids) != len(set(ids)):
            raise ValueError("provided connector ids must be unique within a plugin")
        return self

    def provides(self, connector_id: str) -> bool:
        return any(c.connector_id == connector_id for c in self.provided_connectors)

    def connector(self, connector_id: str) -> ConnectorDescriptor | None:
        for c in self.provided_connectors:
            if c.connector_id == connector_id:
                return c
        return None


@runtime_checkable
class ConnectorPlugin(Protocol):
    """The extension unit. A plugin exposes its descriptor and can create a
    connector instance for one of its provided connector ids. Implemented outside
    the framework; the framework never imports a vendor plugin."""

    def plugin_descriptor(self) -> ConnectorPluginDescriptor: ...

    def create_connector(self, connector_id: str, context: ConnectorContext) -> Connector: ...


class PluginCompatibility:
    """Pure version-compatibility checks between a plugin and this framework."""

    @staticmethod
    def is_compatible(
        descriptor: ConnectorPluginDescriptor, framework_version: Version = FRAMEWORK_VERSION
    ) -> bool:
        return descriptor.framework_compatibility.contains(framework_version)

    @staticmethod
    def assert_compatible(
        descriptor: ConnectorPluginDescriptor, framework_version: Version = FRAMEWORK_VERSION
    ) -> None:
        if not descriptor.framework_compatibility.contains(framework_version):
            raise ConnectorCompatibilityError(
                f"plugin {descriptor.plugin_id!r} supports framework "
                f"{descriptor.framework_compatibility.minimum}.."
                f"{descriptor.framework_compatibility.maximum}; "
                f"this framework is {framework_version}"
            )


class PluginValidation:
    """Pure structural + semantic validation of a plugin descriptor."""

    @staticmethod
    def validate(
        descriptor: ConnectorPluginDescriptor, framework_version: Version = FRAMEWORK_VERSION
    ) -> tuple[str, ...]:
        """Return a deterministic tuple of issue messages ("" empty = valid)."""
        issues: list[str] = []
        if not PluginCompatibility.is_compatible(descriptor, framework_version):
            issues.append(
                f"incompatible with framework {framework_version} "
                f"(supports {descriptor.framework_compatibility.minimum}.."
                f"{descriptor.framework_compatibility.maximum})"
            )
        for connector in descriptor.provided_connectors:
            issues.extend(connector_coherence_issues(connector))
        return tuple(issues)

    @staticmethod
    def assert_valid(
        descriptor: ConnectorPluginDescriptor, framework_version: Version = FRAMEWORK_VERSION
    ) -> None:
        issues = PluginValidation.validate(descriptor, framework_version)
        if issues:
            raise PluginValidationError(
                f"plugin {descriptor.plugin_id!r} is invalid: {'; '.join(issues)}"
            )


class RegisteredPlugin(BaseModel):
    """An immutable registry entry: a plugin's descriptor + its lifecycle state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    descriptor: ConnectorPluginDescriptor
    state: PluginLifecycleState


class ConnectorPluginLoader:
    """In-memory plugin registration model (no filesystem, no entry points, no
    marketplace, no code execution). Validates, checks compatibility, tracks each
    plugin's lifecycle state, and is the **single source of truth** for both
    plugins and their connectors: registering a plugin automatically publishes its
    connector descriptors into an internally-owned `ConnectorRegistry`, and
    unregistering a plugin withdraws exactly those descriptors. There are no two
    independent stores to drift — discover connectors via `discovery()` /
    `connector_descriptors()`, which read that one registry."""

    def __init__(self, framework_version: Version = FRAMEWORK_VERSION) -> None:
        self._framework_version = framework_version
        self._plugins: dict[str, ConnectorPlugin] = {}
        self._states: dict[str, PluginLifecycleState] = {}
        self._registry = ConnectorRegistry()

    def register(self, plugin: ConnectorPlugin) -> None:
        """Validate + compatibility-check + register a plugin **and its
        connectors** in memory, atomically. Advances the plugin lifecycle
        DISCOVERED -> VALIDATED -> REGISTERED -> ENABLED and publishes every
        provided connector descriptor into the owned registry. Raises (leaving the
        loader unchanged) on a duplicate plugin id, a connector-id already provided
        by another registered plugin, incompatibility, or invalidity."""
        descriptor = plugin.plugin_descriptor()
        pid = descriptor.plugin_id
        if pid in self._plugins:
            raise ConnectorRegistrationError(f"plugin {pid!r} is already registered")
        if len(self._plugins) >= MAX_REGISTERED_PLUGINS:
            raise ConnectorRegistrationError("plugin registry is full")
        # Compatibility first (the most specific rejection), then full validation.
        PluginCompatibility.assert_compatible(descriptor, self._framework_version)
        PluginValidation.assert_valid(descriptor, self._framework_version)
        # Atomicity: reject any cross-plugin connector-id collision BEFORE mutating.
        for connector in descriptor.provided_connectors:
            if self._registry.contains(connector.connector_id):
                raise ConnectorRegistrationError(
                    f"connector {connector.connector_id!r} (from plugin {pid!r}) is already "
                    "provided by another registered plugin"
                )
        # Commit: plugin -> ENABLED, and publish its connectors.
        self._plugins[pid] = plugin
        self._states[pid] = PluginLifecycleState.ENABLED
        for connector in descriptor.provided_connectors:
            self._registry.register(connector, plugin_id=pid)

    def unregister(self, plugin_id: str) -> None:
        """Withdraw a plugin **and its connectors** — keeping the plugin store and
        the connector registry consistent (no drift)."""
        if plugin_id not in self._plugins:
            raise ConnectorNotFoundError(f"plugin {plugin_id!r} is not registered")
        descriptor = self._plugins[plugin_id].plugin_descriptor()
        for connector in descriptor.provided_connectors:
            if self._registry.contains(connector.connector_id):
                self._registry.unregister(connector.connector_id)
        del self._plugins[plugin_id]
        del self._states[plugin_id]

    def get(self, plugin_id: str) -> ConnectorPlugin:
        if plugin_id not in self._plugins:
            raise ConnectorNotFoundError(f"plugin {plugin_id!r} is not registered")
        return self._plugins[plugin_id]

    def state_of(self, plugin_id: str) -> PluginLifecycleState:
        if plugin_id not in self._states:
            raise ConnectorNotFoundError(f"plugin {plugin_id!r} is not registered")
        return self._states[plugin_id]

    def set_state(self, plugin_id: str, to_state: PluginLifecycleState) -> None:
        current = self.state_of(plugin_id)
        PluginLifecycle.assert_transition(current, to_state)
        self._states[plugin_id] = to_state

    # --- connectors (the single source of truth; read-only, loader-managed) ---

    def connector_ids(self) -> tuple[str, ...]:
        """Ids of every connector provided by a registered plugin, sorted."""
        return self._registry.connector_ids()

    def connector_descriptors(self) -> tuple[ConnectorDescriptor, ...]:
        """Every connector descriptor from a registered plugin, sorted by id."""
        return self._registry.descriptors()

    def get_connector(self, connector_id: str) -> ConnectorDescriptor:
        """The descriptor for `connector_id`, or raise `ConnectorNotFoundError`."""
        return self._registry.get(connector_id)

    def plugin_id_for_connector(self, connector_id: str) -> str | None:
        """Which registered plugin provides `connector_id` (or raise if unknown)."""
        return self._registry.entry(connector_id).plugin_id

    def discovery(self) -> ConnectorDiscovery:
        """A read-only discovery view over the loader's connector registry — the
        single source of truth, so results never drift from the registered
        plugins."""
        return ConnectorDiscovery(self._registry)

    def plugin_ids(self) -> tuple[str, ...]:
        """Registered plugin ids in stable (sorted) order."""
        return tuple(sorted(self._plugins))

    def descriptors(self) -> tuple[ConnectorPluginDescriptor, ...]:
        return tuple(self._plugins[pid].plugin_descriptor() for pid in sorted(self._plugins))

    def registered(self) -> tuple[RegisteredPlugin, ...]:
        return tuple(
            RegisteredPlugin(
                descriptor=self._plugins[pid].plugin_descriptor(), state=self._states[pid]
            )
            for pid in sorted(self._plugins)
        )
