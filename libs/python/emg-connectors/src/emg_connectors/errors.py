"""Connector framework exception hierarchy (FEAT-13-1).

All framework rejections derive from the platform-wide `emg_errors.EMGError`
hierarchy (via `ConnectorError`), so connector/plugin errors are handled and
logged like every other EMG error. Field-/structure-level rejections raised inside
pydantic validators surface as `pydantic.ValidationError`; the typed errors below
are raised by the registry, factory, negotiator, validator, and lifecycle/
compatibility checks.
"""

from __future__ import annotations

from emg_errors import ValidationError


class ConnectorError(ValidationError):
    """Base for all connector-framework errors."""

    error_code = "CONNECTOR_ERROR"


class ConnectorValidationError(ConnectorError):
    """A descriptor/configuration/plugin failed framework validation."""

    error_code = "CONNECTOR_VALIDATION_ERROR"


class ConnectorConfigurationError(ConnectorError):
    """A configuration is invalid against its declared schema."""

    error_code = "CONNECTOR_CONFIGURATION_ERROR"


class ConnectorCapabilityError(ConnectorError):
    """A capability negotiation failed (a required capability/entity type/sync
    mode/auth mechanism is not supported)."""

    error_code = "CONNECTOR_CAPABILITY_ERROR"


class ConnectorRegistrationError(ConnectorError):
    """A connector/plugin could not be registered (duplicate id, registry full)."""

    error_code = "CONNECTOR_REGISTRATION_ERROR"


class ConnectorNotFoundError(ConnectorError):
    """A requested connector/plugin id is not registered."""

    error_code = "CONNECTOR_NOT_FOUND"


class ConnectorCompatibilityError(ConnectorError):
    """A plugin is not compatible with this framework version."""

    error_code = "CONNECTOR_COMPATIBILITY_ERROR"


class ConnectorLifecycleError(ConnectorError):
    """An illegal connector/plugin lifecycle transition was requested."""

    error_code = "CONNECTOR_LIFECYCLE_ERROR"


class PluginValidationError(ConnectorValidationError):
    """A plugin descriptor is structurally or semantically invalid."""

    error_code = "CONNECTOR_PLUGIN_VALIDATION_ERROR"
