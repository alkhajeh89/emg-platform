"""Configuration schema + configuration validation + auth contract (FEAT-13-1)."""

from __future__ import annotations

import pytest
from emg_connectors import (
    AuthenticationMechanism,
    ConfigField,
    ConfigFieldType,
    ConnectorAuthentication,
    ConnectorConfiguration,
    ConnectorConfigurationSchema,
    ConnectorValidator,
)
from pydantic import ValidationError


def _schema() -> ConnectorConfigurationSchema:
    return ConnectorConfigurationSchema(
        fields=(
            ConfigField(name="host", type=ConfigFieldType.STRING, required=True),
            ConfigField(name="port", type=ConfigFieldType.INTEGER, default=443),
            ConfigField(name="verify_tls", type=ConfigFieldType.BOOLEAN, default=True),
            ConfigField(name="api_key_ref", type=ConfigFieldType.STRING, secret=True),
        )
    )


def test_valid_configuration_has_no_issues() -> None:
    cfg = ConnectorConfiguration(
        connector_id="acme-dir",
        values={"host": "dir.internal", "port": 443, "api_key_ref": "vault://acme/key"},
    )
    assert ConnectorValidator.validate_configuration(_schema(), cfg) == ()
    ConnectorValidator.assert_configuration(_schema(), cfg)  # does not raise


def test_missing_required_reported() -> None:
    cfg = ConnectorConfiguration(connector_id="acme-dir", values={"port": 443})
    issues = ConnectorValidator.validate_configuration(_schema(), cfg)
    assert any("host" in i for i in issues)


def test_type_mismatch_and_unknown_key_reported() -> None:
    cfg = ConnectorConfiguration(
        connector_id="acme-dir", values={"host": "h", "port": "notint", "rogue": 1}
    )
    issues = ConnectorValidator.validate_configuration(_schema(), cfg)
    assert any("port" in i for i in issues)
    assert any("unknown" in i for i in issues)


def test_bool_not_accepted_as_integer() -> None:
    cfg = ConnectorConfiguration(connector_id="acme-dir", values={"host": "h", "port": True})
    issues = ConnectorValidator.validate_configuration(_schema(), cfg)
    assert any("port" in i for i in issues)


def test_secret_field_must_be_string_type() -> None:
    with pytest.raises(ValidationError):
        ConfigField(name="k", type=ConfigFieldType.INTEGER, secret=True)


def test_secret_field_rejects_inline_default() -> None:
    with pytest.raises(ValidationError):
        ConfigField(name="k", type=ConfigFieldType.STRING, secret=True, default="inline-secret")


def test_schema_rejects_duplicate_field_names() -> None:
    with pytest.raises(ValidationError):
        ConnectorConfigurationSchema(
            fields=(
                ConfigField(name="x", type=ConfigFieldType.STRING),
                ConfigField(name="x", type=ConfigFieldType.INTEGER),
            )
        )


def test_config_values_are_immutable() -> None:
    cfg = ConnectorConfiguration(connector_id="acme-dir", values={"host": "h"})
    with pytest.raises(TypeError):
        cfg.values["host"] = "evil"  # type: ignore[index]


# --- authentication contract (no secrets) -----------------------------------


def test_auth_none_default() -> None:
    auth = ConnectorAuthentication()
    assert auth.mechanism is AuthenticationMechanism.NONE
    assert auth.credential_ref is None


def test_auth_requires_credential_ref_for_non_none() -> None:
    with pytest.raises(ValidationError):
        ConnectorAuthentication(mechanism=AuthenticationMechanism.API_KEY)


def test_auth_none_forbids_credential_ref() -> None:
    with pytest.raises(ValidationError):
        ConnectorAuthentication(mechanism=AuthenticationMechanism.NONE, credential_ref="vault://x")


def test_auth_with_ref_ok() -> None:
    auth = ConnectorAuthentication(
        mechanism=AuthenticationMechanism.OAUTH2,
        credential_ref="vault://acme/oauth",
        scopes=("read",),
    )
    assert auth.credential_ref == "vault://acme/oauth"
