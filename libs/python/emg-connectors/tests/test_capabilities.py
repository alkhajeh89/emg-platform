"""Capabilities, negotiation, and feature discovery (FEAT-13-1)."""

from __future__ import annotations

import pytest
from emg_connectors import (
    DEFAULT_CAPABILITY_REGISTRY,
    AuthenticationMechanism,
    CapabilityRequirement,
    ConnectorCapabilities,
    ConnectorCapability,
    SynchronizationMode,
    negotiate,
)
from pydantic import ValidationError


def _caps() -> ConnectorCapabilities:
    return ConnectorCapabilities(
        capabilities=(ConnectorCapability.READ, ConnectorCapability.FULL_SYNC),
        supported_entity_types=("Person", "Organization"),
        supported_sync_modes=(SynchronizationMode.FULL,),
        supported_auth_mechanisms=(AuthenticationMechanism.API_KEY,),
    )


def test_normalisation_is_sorted_unique_deterministic() -> None:
    a = ConnectorCapabilities(
        capabilities=(ConnectorCapability.WRITE, ConnectorCapability.READ, ConnectorCapability.READ)
    )
    b = ConnectorCapabilities(capabilities=(ConnectorCapability.READ, ConnectorCapability.WRITE))
    assert a == b
    assert a.model_dump() == b.model_dump()


def test_supports_helpers() -> None:
    caps = _caps()
    assert caps.supports(ConnectorCapability.READ)
    assert not caps.supports(ConnectorCapability.WRITE)
    assert caps.supports_entity_type("Person")
    assert not caps.supports_entity_type("Nope")
    assert caps.supports_sync_mode(SynchronizationMode.FULL)
    assert caps.supports_auth(AuthenticationMechanism.API_KEY)


def test_auth_must_be_declared() -> None:
    with pytest.raises(ValidationError):
        ConnectorCapabilities(supported_auth_mechanisms=())


def test_negotiate_satisfied() -> None:
    result = negotiate(
        _caps(),
        CapabilityRequirement(
            required_capabilities=(ConnectorCapability.READ,),
            required_entity_types=("Person",),
            required_sync_mode=SynchronizationMode.FULL,
            required_auth_mechanism=AuthenticationMechanism.API_KEY,
        ),
    )
    assert result.satisfied
    assert result.missing_capabilities == ()


def test_negotiate_reports_missing() -> None:
    result = negotiate(
        _caps(),
        CapabilityRequirement(
            required_capabilities=(ConnectorCapability.WRITE, ConnectorCapability.SCHEMA_DISCOVERY),
            required_entity_types=("Investigation",),
            required_sync_mode=SynchronizationMode.INCREMENTAL,
            required_auth_mechanism=AuthenticationMechanism.OAUTH2,
        ),
    )
    assert not result.satisfied
    assert result.missing_capabilities == (
        ConnectorCapability.SCHEMA_DISCOVERY,
        ConnectorCapability.WRITE,
    )
    assert result.missing_entity_types == ("Investigation",)
    assert result.missing_sync_mode is SynchronizationMode.INCREMENTAL
    assert result.missing_auth_mechanism is AuthenticationMechanism.OAUTH2


def test_negotiate_is_deterministic() -> None:
    req = CapabilityRequirement(required_capabilities=(ConnectorCapability.WRITE,))
    assert negotiate(_caps(), req).model_dump() == negotiate(_caps(), req).model_dump()


def test_empty_requirement_is_satisfied() -> None:
    assert negotiate(_caps(), CapabilityRequirement()).satisfied


def test_capability_registry_feature_discovery() -> None:
    reg = DEFAULT_CAPABILITY_REGISTRY
    assert reg.is_known(ConnectorCapability.READ)
    assert set(reg.known_capabilities()) == set(ConnectorCapability)
    assert reg.describe(ConnectorCapability.FULL_SYNC) is not None


def test_capabilities_immutable() -> None:
    caps = _caps()
    with pytest.raises(ValidationError):
        caps.capabilities = ()


# --- FIX 1: extensible (vendor-specific) capabilities -----------------------


def test_extension_capabilities_supported_alongside_standard() -> None:
    caps = ConnectorCapabilities(
        capabilities=(ConnectorCapability.READ,),
        extension_capabilities=("acme:delta_feed", "acme:webhook"),
    )
    assert caps.supports(ConnectorCapability.READ)  # standard still strongly typed
    assert caps.supports_extension("acme:delta_feed")
    assert not caps.supports_extension("acme:unknown")


def test_extension_capabilities_normalised_sorted_unique() -> None:
    a = ConnectorCapabilities(extension_capabilities=("b:y", "a:x", "a:x"))
    b = ConnectorCapabilities(extension_capabilities=("a:x", "b:y"))
    assert a == b and a.model_dump() == b.model_dump()


def test_extension_capability_may_not_reuse_standard_value() -> None:
    with pytest.raises(ValidationError):
        ConnectorCapabilities(extension_capabilities=("read",))  # a standard value


def test_extension_capability_rejects_control_bidi() -> None:
    with pytest.raises(ValidationError):
        ConnectorCapabilities(extension_capabilities=("acme:\x00",))


def test_negotiate_extension_capabilities() -> None:
    caps = ConnectorCapabilities(
        capabilities=(ConnectorCapability.READ,), extension_capabilities=("acme:delta_feed",)
    )
    ok = negotiate(
        caps,
        CapabilityRequirement(
            required_capabilities=(ConnectorCapability.READ,),
            required_extension_capabilities=("acme:delta_feed",),
        ),
    )
    assert ok.satisfied and ok.missing_extension_capabilities == ()

    missing = negotiate(
        caps,
        CapabilityRequirement(required_extension_capabilities=("acme:delta_feed", "acme:absent")),
    )
    assert not missing.satisfied
    assert missing.missing_extension_capabilities == ("acme:absent",)


def test_extension_negotiation_is_deterministic() -> None:
    caps = ConnectorCapabilities(extension_capabilities=("x:a",))
    req = CapabilityRequirement(required_extension_capabilities=("x:b", "x:c"))
    assert negotiate(caps, req).model_dump() == negotiate(caps, req).model_dump()
