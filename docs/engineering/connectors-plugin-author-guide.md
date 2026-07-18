# Plugin Author Guide (EPIC-13 / FEAT-13-1)

A worked, minimal template for authoring a connector plugin. This lives in a
*separate* package that depends on `emg-connectors`; the framework is not modified.
(The example below is illustrative pseudocode — this sprint ships **no** real
connector.)

## 1. Declare capabilities and a descriptor

```python
from emg_connectors import (
    ConnectorCapabilities, ConnectorCapability, SynchronizationMode,
    AuthenticationMechanism, ConnectorDescriptor, Version,
    ConnectorConfigurationSchema, ConfigField, ConfigFieldType,
)

caps = ConnectorCapabilities(
    capabilities=(ConnectorCapability.READ, ConnectorCapability.FULL_SYNC,
                  ConnectorCapability.ENTITY_MAPPING),
    supported_entity_types=("Person", "Organization"),
    supported_sync_modes=(SynchronizationMode.FULL,),
    supported_auth_mechanisms=(AuthenticationMechanism.API_KEY,),
)

schema = ConnectorConfigurationSchema(fields=(
    ConfigField(name="base_path", type=ConfigFieldType.STRING, required=True),
    ConfigField(name="api_key_ref", type=ConfigFieldType.STRING, secret=True),  # opaque ref
))

descriptor = ConnectorDescriptor(
    connector_id="example-directory", name="Example Directory",
    version=Version(major=1, minor=0, patch=0), vendor="example",
    capabilities=caps, configuration_schema=schema,
)
```

## 2. Implement the connector (extend `AbstractConnector`)

```python
from emg_connectors import AbstractConnector, ConnectorHealth, ConnectorHealthStatus

class ExampleConnector(AbstractConnector):
    # The framework base already manages lifecycle + status. Add vendor behaviour
    # here (reading/mapping records). No networking is part of the framework — your
    # plugin owns its transport and its dependencies, entirely outside emg-connectors.
    def report_ready(self, at) -> None:
        self.report_health(ConnectorHealth(status=ConnectorHealthStatus.HEALTHY, checked_at=at))
```

## 3. Implement the plugin (`ConnectorPlugin`)

```python
from emg_connectors import ConnectorPluginDescriptor, VersionRange, ConnectorContext, Connector

class ExamplePlugin:
    def plugin_descriptor(self) -> ConnectorPluginDescriptor:
        return ConnectorPluginDescriptor(
            plugin_id="example", name="Example Plugin",
            version=Version(major=1, minor=0, patch=0), vendor="example",
            framework_compatibility=VersionRange(minimum=Version(major=1, minor=0, patch=0)),
            provided_connectors=(descriptor,),
        )

    def create_connector(self, connector_id: str, context: ConnectorContext) -> Connector:
        return ExampleConnector(descriptor, created_at=context.as_of)
```

## 4. Register and use

Registering the plugin **auto-publishes its connectors** — no separate registry
step, and unregistering withdraws them (single source of truth, no drift).

```python
from emg_connectors import ConnectorPluginLoader, ConnectorFactory, CapabilityRequirement, ConnectorCapability

loader = ConnectorPluginLoader()
loader.register(ExamplePlugin())          # validates + checks compatibility + publishes connectors

# discover via the loader (the one registry):
matches = loader.discovery().satisfying(
    CapabilityRequirement(required_capabilities=(ConnectorCapability.READ,))
)

connector = ConnectorFactory.create(ExamplePlugin(), "example-directory",
                                    ConnectorContext(correlation_id="c1", as_of=now))

loader.unregister("example")              # withdraws the plugin AND its connectors
```

### Vendor-specific capabilities

If your connector supports a capability the core doesn't enumerate, declare it in
`extension_capabilities` (namespaced, e.g. `("example:incremental_delta",)`) on the
`ConnectorCapabilities` — no framework change needed; consumers negotiate it via
`CapabilityRequirement.required_extension_capabilities`.

## Author checklist

- [ ] `plugin_id` and every `connector_id` unique and control/bidi-free.
- [ ] Declared sync capabilities match declared sync modes; `DELETE_DETECTION`
      implies `CHANGE_DETECTION` (else `PluginValidation` fails).
- [ ] `framework_compatibility` includes the target `FRAMEWORK_VERSION`.
- [ ] Secrets are opaque references (`credential_ref` / a `secret` string field),
      never inline values.
- [ ] Configuration validated with `ConnectorValidator.validate_configuration`.
- [ ] All vendor SDKs / transport / auth live in **your** package — never in
      `emg-connectors`.

## Boundaries (do not do in a plugin that ships with the core)

The framework repository ships no real connector. Vendor plugins (SAP, Oracle,
SharePoint, Teams, Outlook, Copilot, Dynamics, Salesforce, ServiceNow, Jira,
Confluence, GitHub Enterprise, Google Workspace, custom) are authored and
distributed independently and never require a core change.
