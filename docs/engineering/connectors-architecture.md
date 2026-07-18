# Universal Connector Framework — Architecture (EPIC-13 / FEAT-13-1)

> **Backlog note.** This is an *additive* roadmap item under the next free
> identifiers **EPIC-13 (Enterprise Integration Platform) / FEAT-13-1 (Universal
> Connector Framework)**. The frozen Engineering Backlog's `EPIC-06 = Search` and
> `FEAT-06-1 … 06-5` are unchanged; no existing item was modified or renumbered.

Delivered library-first as `libs/python/emg-connectors` (Sprint 14). A **storage-,
vendor-, and protocol-independent, contracts-only** foundation for every future
enterprise integration.

## Principles

- **Interface-driven / contracts only.** The framework defines *what* a connector
  and a plugin must expose and *how* they are registered, negotiated, and
  validated — never *how* to talk to a real system.
- **No external anything.** No networking, persistence, authentication, HTTP
  client, message queue, CLI, UI, or cloud/vendor SDK. Nothing is executed against
  any external system.
- **No vendor branching.** The core contains no `if SAP`, `if Oracle`, `if
  SharePoint`, `if Jira`, … A test (`test_core_has_no_vendor_branching`) strips
  strings/comments from every core module and asserts no vendor token appears in
  executable code.
- **Immutability where applicable.** Every descriptor, capability set,
  configuration, event, decision, and result is a frozen pydantic model with
  `extra="forbid"`; the one stateful object is a connector *instance* (its
  lifecycle state).
- **Deterministic.** No wall-clock (timestamps are supplied by callers), no
  randomness, no mutable global state; normalised collections give stable
  equality/serialisation.
- **Bounded.** Every user-/plugin-supplied collection and string is length-bounded
  (`limits.py`); identifiers are validated against control/bidi characters
  (`labels.py`).

## Module map (no cyclic dependencies)

```
limits ─┐
labels ─┤ (identifier validation)
version ┤ (semver + ranges + FRAMEWORK_VERSION)
enums  ─┤ (closed vocabularies)
errors ─┘ (ConnectorError hierarchy)
        ▼
capabilities  configuration  metadata  health  events  mapping  synchronization
        ▼
context  →  connector (Connector protocol + AbstractConnector)
        ▼
lifecycle (ConnectorLifecycle, PluginLifecycle)
        ▼
validation (ConnectorValidator, connector_coherence_issues)
        ▼
plugin (ConnectorPlugin, ConnectorPluginDescriptor, PluginValidation,
        PluginCompatibility, ConnectorPluginLoader)
        ▼
registry (ConnectorRegistry)   factory (ConnectorFactory)   discovery (ConnectorDiscovery)
```

`import emg_connectors` runs cleanly with a single dependency layer per module and
no import cycles (verified by mypy --strict and by import at collection time).

## The two contracts

- **Connector contract** (`Connector` protocol + `AbstractConnector` base): what a
  running connector exposes — descriptor, capabilities, configuration schema,
  health, statistics, status, and a managed lifecycle. Implemented by a plugin.
- **Plugin contract** (`ConnectorPlugin` protocol + `ConnectorPluginDescriptor`):
  the extension unit — a plugin declares its identity, the framework version range
  it supports, and the connector descriptors it provides, and can create connector
  instances. Implemented outside the framework; the core never imports a vendor
  plugin.

## Separation of concerns

Connector contract · Plugin contract · Plugin registration (`ConnectorPluginLoader`)
· Plugin/feature discovery metadata (`ConnectorDiscovery`, `CapabilityRegistry`) ·
Connector instantiation (`ConnectorFactory`) · Capability negotiation
(`negotiate`) · Version compatibility (`PluginCompatibility`, `Version`,
`VersionRange`) · Lifecycle management (`ConnectorLifecycle`, `PluginLifecycle`) —
each isolated in its own module.

### Single source of truth for connectors

`ConnectorPluginLoader` owns one internal `ConnectorRegistry`. Registering a
plugin atomically publishes its connector descriptors into that registry;
unregistering withdraws exactly those descriptors. There is **no** second,
independently-populated registry to keep in sync — so the set of live plugins and
the set of discoverable connectors cannot drift. Cross-plugin `connector_id`
collisions are rejected before any state is committed (all-or-nothing).
`loader.discovery()`, `loader.connector_ids()`, `loader.connector_descriptors()`,
`loader.get_connector(id)`, and `loader.plugin_id_for_connector(id)` all read that
one registry. The standalone `ConnectorRegistry` / `ConnectorDiscovery` remain
available as lower-level primitives, but are no longer required for the normal
register→discover→create flow.

### Extensible capabilities

Standard capabilities are the closed, strongly-typed `ConnectorCapability` enum.
Vendors declare capabilities the core does not enumerate via free-form,
safe-label-validated `extension_capabilities` (namespaced strings) on
`ConnectorCapabilities` — an open extension point that requires **no** change to
the framework and cannot reuse a standard capability value. `negotiate` resolves
standard and extension capabilities symmetrically
(`missing_extension_capabilities`).

## Dependencies

`emg-common-types`, `emg-errors`, `pydantic` only. **Not** `emg-ontology`,
`emg-semantic-layer`, `emg-knowledge-pipeline`, or `emg-trust-scoring`. Zero reverse
dependencies (nothing imports it yet).

## Security posture

Malformed descriptors/configurations/plugins are rejected at construction
(`pydantic.ValidationError`) or by the typed `ConnectorError` hierarchy;
identifiers reject control/bidi characters (no injection surface); authentication
carries only an **opaque credential reference**, never a raw secret; collections
are bounded (no unbounded payloads); registries and negotiation are pure and
deterministic. Full detail in `security-limitations.md` (Sprint 14 section).
