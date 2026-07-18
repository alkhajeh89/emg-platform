# Extension Guide (EPIC-13 / FEAT-13-1)

How the framework is extended **without modifying the core**. Everything here is
in-process and contract-driven; nothing in this sprint loads code dynamically.

## Extension points

1. **`ConnectorPlugin`** (protocol) — the primary extension unit. Implement it to
   add one or more connectors. It exposes a `ConnectorPluginDescriptor` and can
   `create_connector(connector_id, context)`.
2. **`AbstractConnector`** (base class) — extend it to implement a connector's
   behaviour; it already manages the lifecycle state machine and health/statistics
   snapshots, so a plugin author focuses on vendor behaviour only.
3. **Mapper protocols** — `EntityMapper`, `RelationshipMapper`, `MetadataMapper`
   map a neutral `SourceRecord` onto neutral `MappedEntity` / `MappedRelationship`
   / `MappedMetadata`. Implement the ones your connector supports.
4. **Capabilities** — declare support via `ConnectorCapabilities` (capabilities,
   entity types, sync modes, auth mechanisms). `CapabilityRegistry` catalogues the
   framework-known capabilities for feature discovery.
5. **Configuration schema** — declare a `ConnectorConfigurationSchema` of typed
   `ConfigField`s; deployments supply a `ConnectorConfiguration` validated by
   `ConnectorValidator`.

## What you never touch

You never modify `emg_connectors` to add a connector. There is no vendor switch,
enum member, or `if`-branch to edit. A new integration is a new package that
depends on `emg-connectors` and implements `ConnectorPlugin`.

## Registration & discovery flow

`ConnectorPluginLoader` is the **single source of truth**: registering a plugin
automatically publishes its connector descriptors, and unregistering it withdraws
exactly those descriptors — there is no separate `ConnectorRegistry.register`
step to keep in sync, and no two stores that can drift.

```
plugin ─▶ ConnectorPluginLoader.register(plugin)
              │  (PluginCompatibility + PluginValidation, atomic)
              ▼
        plugin ENABLED  +  its connectors auto-published into the loader's registry
              ▼
        loader.discovery().satisfying(requirement)  ─▶ matching descriptors
              ▼
        ConnectorFactory.create(plugin, connector_id, context) ─▶ Connector
              ▼
        loader.unregister(plugin)  ─▶ plugin AND its connectors withdrawn (no drift)
```

`loader.connector_ids()`, `loader.connector_descriptors()`,
`loader.get_connector(id)`, `loader.plugin_id_for_connector(id)`, and
`loader.discovery()` all read that one registry. (The standalone `ConnectorRegistry`
remains available as a lower-level primitive for callers who want to build one by
hand, but the loader no longer requires it.)

## Capabilities: standard + vendor extensions

Standard capabilities are the strongly-typed `ConnectorCapability` enum. A
connector that needs a capability the core does not enumerate declares it in
`extension_capabilities` — free-form (safe-label-validated) strings, conventionally
namespaced (`"acme:incremental_delta"`) — **without editing the framework**. A
standard capability value may not be reused as an extension. Both are negotiated:

```python
from emg_connectors import CapabilityRequirement, ConnectorCapability, negotiate
req = CapabilityRequirement(
    required_capabilities=(ConnectorCapability.READ, ConnectorCapability.INCREMENTAL_SYNC),
    required_extension_capabilities=("acme:incremental_delta",),
)
result = negotiate(descriptor.capabilities, req)
if not result.satisfied:
    ...  # result.missing_capabilities / missing_extension_capabilities /
         # missing_entity_types / missing_sync_mode / missing_auth_mechanism
```

## Version compatibility

A plugin declares `framework_compatibility: VersionRange`. `PluginCompatibility`
checks the framework's `FRAMEWORK_VERSION` against it; `ConnectorPluginLoader` and
`ConnectorFactory` reject an incompatible plugin with `ConnectorCompatibilityError`.

## Rules for a well-formed plugin

- Unique `plugin_id`; ≥ 1 provided connector; unique connector ids within the
  plugin.
- Declared sync capabilities must match declared sync modes (e.g.
  `INCREMENTAL_SYNC` capability ⇒ `INCREMENTAL` mode); `DELETE_DETECTION` requires
  `CHANGE_DETECTION`. `PluginValidation` enforces these.
- Identifiers/labels must be non-empty and free of control/bidi characters.
- Secrets are never inline: an authenticating connector declares a mechanism and an
  **opaque `credential_ref`**.
