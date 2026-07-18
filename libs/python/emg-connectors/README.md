# emg-connectors

**Universal Connector Framework** — Enterprise Integration Platform, **EPIC-13,
FEAT-13-1**, added Sprint 14.

> **Backlog note.** The frozen Engineering Backlog's `EPIC-06 = Search` and
> `FEAT-06-1 = Lexical Search` are **unchanged**. This framework is an *additive*
> roadmap item filed under the next free identifiers (**EPIC-13 / FEAT-13-1**); no
> existing Backlog item was modified or renumbered.

Part of the EMG™ shared-libraries workspace (Module 3, ADR-012), delivered
**library-first**: a **storage-, vendor-, and protocol-independent, contracts-only**
foundation for every future enterprise integration.

It **implements no real system and executes nothing external**: **no networking,
no persistence, no authentication, no HTTP client, no message queue, and no vendor
SDK** (SAP, Oracle, SharePoint, Microsoft 365, Teams, Outlook, Copilot, Dynamics,
Salesforce, ServiceNow, Jira, Confluence, GitHub Enterprise, Google Workspace, …).
The core contains **no vendor branching** — every real connector is added as an
independently registered **plugin** without modifying the framework.

## What this is

- **Connector contract** (`connector.py`): the `Connector` protocol and a
  vendor-neutral `AbstractConnector` base a plugin extends (holds the descriptor,
  manages the lifecycle state machine, exposes health/statistics/status — no
  vendor logic, no I/O).
- **Descriptor** (`metadata.py`): `ConnectorDescriptor` — the central static
  declaration every connector exposes (id, name, version, vendor, capabilities,
  configuration schema, metadata).
- **Capabilities & negotiation** (`capabilities.py`): `ConnectorCapabilities`,
  `CapabilityRequirement`, `negotiate(...) -> CapabilityNegotiation`, and
  `CapabilityRegistry` (feature discovery). Standard capabilities are the closed
  `ConnectorCapability` enum; vendors add capabilities the core does not enumerate
  via free-form, namespaced `extension_capabilities` — no framework change, and
  they cannot reuse a standard value. Negotiation resolves both symmetrically.
- **Configuration & auth** (`configuration.py`): `ConnectorConfigurationSchema` /
  `ConfigField` / `ConnectorConfiguration`, and `ConnectorAuthentication` — a
  *declaration* of the mechanism plus an **opaque credential reference** (never a
  raw secret).
- **Context/session, health/statistics/status, events/changes/snapshots**
  (`context.py`, `health.py`, `events.py`): immutable value objects.
- **Mapping** (`mapping.py`): `SourceRecord` and neutral `MappedEntity` /
  `MappedRelationship` / `MappedMetadata`, with `EntityMapper` /
  `RelationshipMapper` / `MetadataMapper` protocols (no ontology dependency).
- **Synchronization** (`synchronization.py`): `SynchronizationContract`,
  `SynchronizationPolicy`, and `FullSynchronization` / `IncrementalSynchronization`
  *plans* — contracts only; the framework runs no sync and schedules nothing.
- **Lifecycle** (`lifecycle.py`): fixed, deterministic `ConnectorLifecycle` and
  `PluginLifecycle` state machines.
- **Plugin architecture** (`plugin.py`): `ConnectorPlugin`,
  `ConnectorPluginDescriptor`, `PluginValidation`, `PluginCompatibility`, and the
  **in-memory** `ConnectorPluginLoader` — the **single source of truth**:
  registering a plugin auto-publishes its connectors and unregistering withdraws
  them, so plugins and discoverable connectors cannot drift.
- **Registry / factory / discovery / validation** (`registry.py`, `factory.py`,
  `discovery.py`, `validation.py`): `ConnectorRegistry`, `ConnectorFactory`,
  `ConnectorDiscovery`, `ConnectorValidator` — lower-level primitives; the loader
  owns one registry internally and exposes `discovery()` / `connector_ids()` /
  `connector_descriptors()` / `get_connector()` / `plugin_id_for_connector()`.

## What this is not

- **Not a real connector.** No SAP/Oracle/SharePoint/Teams/Outlook/Copilot/
  Salesforce/Jira/ServiceNow/etc. — those are future plugins.
- **Not networking, persistence, authentication, an HTTP client, a queue, a CLI,
  a UI, or any cloud SDK.** Nothing here connects to, or executes against, any
  external system.
- **Not dynamic plugin loading.** No filesystem scanning, entry points, package
  installation, marketplaces, or runtime code execution — registration is
  in-memory only. Those are deliberately deferred.

## Separation of concerns

The framework cleanly separates: the **connector contract**, the **plugin
contract**, **plugin registration**, **plugin/feature discovery metadata**,
**connector instantiation**, **capability negotiation**, **version
compatibility**, and **lifecycle management** — each in its own module, with no
cyclic dependencies.

## Adding a connector (future plugin author)

Implement `ConnectorPlugin` (declare a `ConnectorPluginDescriptor` with your
connector descriptor(s) and a framework version range; implement
`create_connector`). Register it into a `ConnectorPluginLoader` — its connectors
become discoverable automatically, no separate registry step. No framework code
changes. See `docs/engineering/connectors-plugin-author-guide.md`.

## Usage

```python
from emg_connectors import (
    Version, VersionRange,
    ConnectorDescriptor, ConnectorCapabilities, ConnectorCapability, SynchronizationMode,
    ConnectorPluginDescriptor, ConnectorPluginLoader,
    CapabilityRequirement,
)

caps = ConnectorCapabilities(
    capabilities=(ConnectorCapability.READ, ConnectorCapability.FULL_SYNC),
    supported_entity_types=("Person", "Organization"),
    supported_sync_modes=(SynchronizationMode.FULL,),
    extension_capabilities=("acme:delta_feed",),   # vendor-specific, no framework change
)
descriptor = ConnectorDescriptor(
    connector_id="acme-directory", name="Acme Directory", version=Version(major=1, minor=0, patch=0),
    vendor="acme", capabilities=caps,
)

# A plugin exposing that descriptor auto-publishes it on registration:
loader = ConnectorPluginLoader()
loader.register(my_plugin)                       # my_plugin.plugin_descriptor().provided_connectors == (descriptor,)
found = loader.discovery().satisfying(
    CapabilityRequirement(required_capabilities=(ConnectorCapability.READ,))
)
assert found[0].connector_id == "acme-directory"
```
