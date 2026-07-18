"""Connector factory (FEAT-13-1).

`ConnectorFactory` turns a registered plugin + a connector id + a context into a
`Connector` instance, via the plugin's own `create_connector`. It is pure
orchestration: it checks framework compatibility, verifies the plugin provides the
requested connector, delegates construction to the plugin (in-process — **not**
dynamic loading), and verifies the returned connector's identity. The framework
constructs no vendor object itself.
"""

from __future__ import annotations

from .connector import Connector
from .context import ConnectorContext
from .errors import ConnectorNotFoundError, ConnectorValidationError
from .plugin import ConnectorPlugin, PluginCompatibility
from .version import FRAMEWORK_VERSION, Version


class ConnectorFactory:
    """Creates connector instances from registered plugins. Stateless."""

    @staticmethod
    def create(
        plugin: ConnectorPlugin,
        connector_id: str,
        context: ConnectorContext,
        *,
        framework_version: Version = FRAMEWORK_VERSION,
    ) -> Connector:
        """Instantiate `connector_id` from `plugin`. Raises
        `ConnectorCompatibilityError` if the plugin is incompatible,
        `ConnectorNotFoundError` if it does not provide the id, and
        `ConnectorValidationError` if the produced connector's identity mismatches."""
        descriptor = plugin.plugin_descriptor()
        PluginCompatibility.assert_compatible(descriptor, framework_version)
        if not descriptor.provides(connector_id):
            raise ConnectorNotFoundError(
                f"plugin {descriptor.plugin_id!r} does not provide connector {connector_id!r}"
            )
        connector = plugin.create_connector(connector_id, context)
        produced = connector.descriptor().connector_id
        if produced != connector_id:
            raise ConnectorValidationError(
                f"plugin {descriptor.plugin_id!r} produced connector {produced!r} "
                f"for requested id {connector_id!r}"
            )
        return connector
