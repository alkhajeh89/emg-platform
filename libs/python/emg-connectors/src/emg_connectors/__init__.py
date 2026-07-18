"""emg_connectors — the Universal Connector Framework (Enterprise Integration
Platform, EPIC-13, FEAT-13-1). Added Sprint 14.

Library-first, the same contract-first pattern as the Module 7 libraries: a
**storage-, vendor-, and protocol-independent, contracts-only** foundation for
every future enterprise integration. It defines the connector and plugin
contracts, an in-memory registry + factory, capability negotiation, version
compatibility, lifecycle state machines, and synchronization contracts.

It **implements no real system and executes nothing external**: no networking, no
persistence, no authentication, no HTTP client, and no vendor SDK (SAP, Oracle,
SharePoint, Microsoft 365, Teams, Outlook, Copilot, Dynamics, Salesforce,
ServiceNow, Jira, Confluence, GitHub Enterprise, Google Workspace, …). The core
contains **no vendor branching** (`if SAP`, `if Oracle`, …); every real connector
is added as an independently registered **plugin** without modifying the core.

Plugin discovery is storage- and networking-independent: this sprint provides the
contracts, validation, registry behaviour, compatibility checks, and an in-memory
plugin-registration model — **not** dynamic filesystem scanning, Python
entry-point loading, package installation, remote marketplaces, or runtime code
execution.

Naming note: the frozen Engineering Backlog's EPIC-06 = Search / FEAT-06-1 =
Lexical Search are unchanged. This framework is an **additive** roadmap item filed
under the next free identifiers (EPIC-13 / FEAT-13-1); the frozen Backlog file is
not modified.
"""

from .capabilities import (
    DEFAULT_CAPABILITY_REGISTRY,
    CapabilityNegotiation,
    CapabilityRegistry,
    CapabilityRequirement,
    ConnectorCapabilities,
    FeatureDescriptor,
    negotiate,
)
from .configuration import (
    ConfigField,
    ConfigFieldType,
    ConnectorAuthentication,
    ConnectorConfiguration,
    ConnectorConfigurationSchema,
    ScalarValue,
)
from .connector import AbstractConnector, Connector
from .context import ConnectorContext, ConnectorSession
from .discovery import ConnectorDiscovery
from .enums import (
    AuthenticationMechanism,
    ChangeType,
    ConnectorCapability,
    ConnectorEventType,
    ConnectorHealthStatus,
    ConnectorLifecycleState,
    PluginLifecycleState,
    SynchronizationMode,
)
from .errors import (
    ConnectorCapabilityError,
    ConnectorCompatibilityError,
    ConnectorConfigurationError,
    ConnectorError,
    ConnectorLifecycleError,
    ConnectorNotFoundError,
    ConnectorRegistrationError,
    ConnectorValidationError,
    PluginValidationError,
)
from .events import ConnectorChange, ConnectorEvent, ConnectorSnapshot
from .factory import ConnectorFactory
from .health import ConnectorHealth, ConnectorStatistics, ConnectorStatus
from .labels import ensure_safe_label
from .lifecycle import ConnectorLifecycle, PluginLifecycle
from .mapping import (
    ConnectorMapper,
    EntityMapper,
    MappedEntity,
    MappedMetadata,
    MappedRelationship,
    MetadataMapper,
    RelationshipMapper,
    SourceRecord,
)
from .metadata import ConnectorDescriptor, ConnectorMetadata
from .plugin import (
    ConnectorPlugin,
    ConnectorPluginDescriptor,
    ConnectorPluginLoader,
    PluginCompatibility,
    PluginValidation,
    RegisteredPlugin,
)
from .registry import ConnectorRegistry, RegisteredConnector
from .synchronization import (
    FullSynchronization,
    IncrementalSynchronization,
    SynchronizationContract,
    SynchronizationPolicy,
)
from .validation import ConnectorValidator, connector_coherence_issues
from .version import FRAMEWORK_VERSION, Version, VersionRange

__version__ = "0.1.0"

__all__ = [
    # version / compatibility
    "Version",
    "VersionRange",
    "FRAMEWORK_VERSION",
    # enums
    "ConnectorCapability",
    "SynchronizationMode",
    "AuthenticationMechanism",
    "ChangeType",
    "ConnectorEventType",
    "ConnectorHealthStatus",
    "ConnectorLifecycleState",
    "PluginLifecycleState",
    # capabilities + negotiation + feature discovery
    "ConnectorCapabilities",
    "CapabilityRequirement",
    "CapabilityNegotiation",
    "negotiate",
    "CapabilityRegistry",
    "FeatureDescriptor",
    "DEFAULT_CAPABILITY_REGISTRY",
    # configuration + auth
    "ConfigFieldType",
    "ConfigField",
    "ConnectorConfigurationSchema",
    "ConnectorConfiguration",
    "ConnectorAuthentication",
    "ScalarValue",
    # descriptor / metadata
    "ConnectorMetadata",
    "ConnectorDescriptor",
    # context / session
    "ConnectorContext",
    "ConnectorSession",
    # health / stats / status
    "ConnectorHealth",
    "ConnectorStatistics",
    "ConnectorStatus",
    # events / changes / snapshots
    "ConnectorEvent",
    "ConnectorChange",
    "ConnectorSnapshot",
    # mapping
    "SourceRecord",
    "MappedEntity",
    "MappedRelationship",
    "MappedMetadata",
    "ConnectorMapper",
    "EntityMapper",
    "RelationshipMapper",
    "MetadataMapper",
    # synchronization
    "SynchronizationContract",
    "SynchronizationPolicy",
    "FullSynchronization",
    "IncrementalSynchronization",
    # connector contract + base + factory
    "Connector",
    "AbstractConnector",
    "ConnectorFactory",
    # lifecycle
    "ConnectorLifecycle",
    "PluginLifecycle",
    # plugin architecture
    "ConnectorPlugin",
    "ConnectorPluginDescriptor",
    "ConnectorPluginLoader",
    "PluginValidation",
    "PluginCompatibility",
    "RegisteredPlugin",
    # registry + discovery + validation
    "ConnectorRegistry",
    "RegisteredConnector",
    "ConnectorDiscovery",
    "ConnectorValidator",
    "connector_coherence_issues",
    # errors
    "ConnectorError",
    "ConnectorValidationError",
    "ConnectorConfigurationError",
    "ConnectorCapabilityError",
    "ConnectorRegistrationError",
    "ConnectorNotFoundError",
    "ConnectorCompatibilityError",
    "ConnectorLifecycleError",
    "PluginValidationError",
    # helpers
    "ensure_safe_label",
    # version
    "__version__",
]
