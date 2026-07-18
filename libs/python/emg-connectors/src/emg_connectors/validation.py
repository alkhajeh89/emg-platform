"""Connector validation (FEAT-13-1).

`ConnectorValidator` is the aggregate, pure validation surface: descriptor
coherence, configuration-against-schema, and synchronization-plan-against-contract
— each available as a non-raising `validate_*` (returns a deterministic tuple of
issue messages) and a raising `assert_*`. It also exposes capability negotiation.
No I/O, no vendor branching.
"""

from __future__ import annotations

from .capabilities import CapabilityNegotiation, CapabilityRequirement, negotiate
from .configuration import ConnectorConfiguration, ConnectorConfigurationSchema, _matches
from .enums import ConnectorCapability, SynchronizationMode
from .errors import (
    ConnectorCapabilityError,
    ConnectorConfigurationError,
    ConnectorValidationError,
)
from .metadata import ConnectorDescriptor
from .synchronization import SynchronizationContract, SynchronizationPolicy


def connector_coherence_issues(descriptor: ConnectorDescriptor) -> list[str]:
    """Deterministic list of internal-coherence issues in a descriptor's declared
    capabilities (e.g. a sync capability not reflected in the sync modes)."""
    issues: list[str] = []
    caps = descriptor.capabilities
    cid = descriptor.connector_id
    if caps.supports(ConnectorCapability.FULL_SYNC) and not caps.supports_sync_mode(
        SynchronizationMode.FULL
    ):
        issues.append(f"{cid}: declares full_sync capability but not FULL sync mode")
    if caps.supports(ConnectorCapability.INCREMENTAL_SYNC) and not caps.supports_sync_mode(
        SynchronizationMode.INCREMENTAL
    ):
        issues.append(f"{cid}: declares incremental_sync capability but not INCREMENTAL sync mode")
    if caps.supports(ConnectorCapability.DELETE_DETECTION) and not caps.supports(
        ConnectorCapability.CHANGE_DETECTION
    ):
        issues.append(f"{cid}: declares delete_detection without change_detection")
    return issues


class ConnectorValidator:
    """Stateless, deterministic validation of connector descriptors,
    configurations, synchronization plans, and capability requirements."""

    @staticmethod
    def validate_descriptor(descriptor: ConnectorDescriptor) -> tuple[str, ...]:
        return tuple(connector_coherence_issues(descriptor))

    @staticmethod
    def assert_descriptor(descriptor: ConnectorDescriptor) -> None:
        issues = ConnectorValidator.validate_descriptor(descriptor)
        if issues:
            raise ConnectorValidationError(
                f"connector {descriptor.connector_id!r} is incoherent: {'; '.join(issues)}"
            )

    @staticmethod
    def validate_configuration(
        schema: ConnectorConfigurationSchema, configuration: ConnectorConfiguration
    ) -> tuple[str, ...]:
        issues: list[str] = []
        known = {f.name: f for f in schema.fields}
        for key in configuration.values:
            if key not in known:
                issues.append(f"unknown configuration key {key!r}")
        for field in schema.fields:
            present = field.name in configuration.values
            value = configuration.values.get(field.name)
            if field.required and (not present or value is None):
                issues.append(f"required field {field.name!r} is missing")
                continue
            if present and value is not None and not _matches(field.type, value):
                issues.append(
                    f"field {field.name!r} expects {field.type.value}, got {type(value).__name__}"
                )
            if present and field.secret and value is not None and not isinstance(value, str):
                issues.append(f"secret field {field.name!r} must be a string reference")
        return tuple(sorted(issues))

    @staticmethod
    def assert_configuration(
        schema: ConnectorConfigurationSchema, configuration: ConnectorConfiguration
    ) -> None:
        issues = ConnectorValidator.validate_configuration(schema, configuration)
        if issues:
            raise ConnectorConfigurationError(
                f"configuration for {configuration.connector_id!r} is invalid: "
                f"{'; '.join(issues)}"
            )

    @staticmethod
    def validate_synchronization(
        contract: SynchronizationContract, policy: SynchronizationPolicy
    ) -> tuple[str, ...]:
        issues: list[str] = []
        if not contract.supports(policy.mode):
            issues.append(f"contract does not support sync mode {policy.mode.value}")
        if policy.mode is SynchronizationMode.INCREMENTAL and not contract.supports_cursor:
            issues.append("incremental sync requires cursor support")
        if policy.allow_deletes and not contract.supports_delete_detection:
            issues.append("policy allows deletes but contract lacks delete detection")
        return tuple(issues)

    @staticmethod
    def assert_synchronization(
        contract: SynchronizationContract, policy: SynchronizationPolicy
    ) -> None:
        issues = ConnectorValidator.validate_synchronization(contract, policy)
        if issues:
            raise ConnectorValidationError(
                f"synchronization policy is invalid: {'; '.join(issues)}"
            )

    @staticmethod
    def negotiate(
        descriptor: ConnectorDescriptor, requirement: CapabilityRequirement
    ) -> CapabilityNegotiation:
        return negotiate(descriptor.capabilities, requirement)

    @staticmethod
    def assert_satisfies(
        descriptor: ConnectorDescriptor, requirement: CapabilityRequirement
    ) -> None:
        result = negotiate(descriptor.capabilities, requirement)
        if not result.satisfied:
            raise ConnectorCapabilityError(
                f"connector {descriptor.connector_id!r} does not satisfy requirement: "
                f"missing capabilities={[c.value for c in result.missing_capabilities]}, "
                f"entity_types={list(result.missing_entity_types)}, "
                f"sync_mode={result.missing_sync_mode}, auth={result.missing_auth_mechanism}"
            )
