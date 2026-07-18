"""Closed enumerations for the connector framework (FEAT-13-1).

Every capability, mechanism, mode, state, and event kind is a **closed enum**,
never a caller-supplied string. Capabilities and mechanisms are *declarations of
support* — the framework enumerates the vocabulary a connector may claim; it does
**not** implement any of them (no auth, no transport, no vendor logic). These
enums are intentionally vendor-neutral: there is no SAP/Oracle/SharePoint member,
and the core never branches on a vendor.
"""

from __future__ import annotations

from enum import Enum


class ConnectorCapability(str, Enum):
    """A capability a connector may declare it supports. Vendor-neutral."""

    READ = "read"
    WRITE = "write"
    FULL_SYNC = "full_sync"
    INCREMENTAL_SYNC = "incremental_sync"
    CHANGE_DETECTION = "change_detection"
    DELETE_DETECTION = "delete_detection"
    SCHEMA_DISCOVERY = "schema_discovery"
    ENTITY_MAPPING = "entity_mapping"
    RELATIONSHIP_MAPPING = "relationship_mapping"
    METADATA_MAPPING = "metadata_mapping"
    SNAPSHOTTING = "snapshotting"
    HEALTH_CHECK = "health_check"
    STATISTICS = "statistics"


class SynchronizationMode(str, Enum):
    """How a synchronization enumerates source data. Contract-level only."""

    FULL = "full"
    INCREMENTAL = "incremental"


class AuthenticationMechanism(str, Enum):
    """An authentication *mechanism a connector declares support for*. The
    framework implements none of these — it records only which a connector can
    use, so a deployment can supply credentials out-of-band."""

    NONE = "none"
    API_KEY = "api_key"
    BASIC = "basic"
    BEARER_TOKEN = "bearer_token"
    OAUTH2 = "oauth2"
    CERTIFICATE = "certificate"
    KERBEROS = "kerberos"
    SAML = "saml"
    CUSTOM = "custom"


class ChangeType(str, Enum):
    """The kind of change a `ConnectorChange` describes."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ConnectorEventType(str, Enum):
    """The kind of lifecycle/operational event a `ConnectorEvent` records."""

    REGISTERED = "registered"
    CONFIGURED = "configured"
    VALIDATED = "validated"
    ACTIVATED = "activated"
    PAUSED = "paused"
    STOPPED = "stopped"
    RETIRED = "retired"
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    CHANGE_DETECTED = "change_detected"
    SNAPSHOT_TAKEN = "snapshot_taken"
    HEALTH_CHANGED = "health_changed"
    ERROR = "error"


class ConnectorHealthStatus(str, Enum):
    """A connector's declared health level (a value object; no probe is run)."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ConnectorLifecycleState(str, Enum):
    """The managed lifecycle state of a connector *instance*."""

    REGISTERED = "registered"  # descriptor known to the registry
    CONFIGURED = "configured"  # a validated configuration is bound
    VALIDATED = "validated"  # configuration + capabilities validated
    ACTIVE = "active"  # in service
    PAUSED = "paused"  # temporarily suspended
    STOPPED = "stopped"  # cleanly stopped
    FAILED = "failed"  # entered an error state
    RETIRED = "retired"  # end of managed life


class PluginLifecycleState(str, Enum):
    """The managed lifecycle state of a registered plugin."""

    DISCOVERED = "discovered"  # descriptor known (in-memory registration)
    VALIDATED = "validated"  # passed PluginValidation
    REGISTERED = "registered"  # accepted into the registry
    ENABLED = "enabled"  # available for connector instantiation
    DISABLED = "disabled"  # registered but not available
    RETIRED = "retired"  # removed from availability
