"""Secret redaction tests (Required Security Control: "Secret redaction in
logs"). Covers redact.py directly and its use in the /federation/providers
response (FederationProviderConfig.redacted_connection_settings)."""

from __future__ import annotations

from emg_identity.federation import FederationProviderConfig, FederationProviderType
from emg_identity.redact import is_sensitive_key, redact_mapping, redact_text, redact_value


def test_is_sensitive_key_matches_common_secret_shaped_names():
    for key in ("secret", "client_secret", "PASSWORD", "bind_dn", "api_token", "private_key"):
        assert is_sensitive_key(key), f"expected {key!r} to be flagged as sensitive"


def test_is_sensitive_key_does_not_match_ordinary_names():
    for key in ("url", "display_name", "username", "provider_type"):
        assert not is_sensitive_key(key)


def test_redact_value_masks_non_empty_values():
    assert redact_value("hunter2") == "***REDACTED***"


def test_redact_value_leaves_empty_and_none_untouched():
    assert redact_value("") == ""
    assert redact_value(None) is None


def test_redact_mapping_only_redacts_sensitive_keys():
    data = {
        "url": "ldaps://ldap.example.internal",
        "bind_dn": "cn=svc,dc=example",
        "bind_password": "hunter2",
    }
    redacted = redact_mapping(data)
    assert redacted["url"] == "ldaps://ldap.example.internal"
    assert redacted["bind_dn"] == "***REDACTED***"
    assert redacted["bind_password"] == "***REDACTED***"


def test_redact_text_masks_secret_shaped_substrings():
    text = '{"client_id": "svc-1", "client_secret": "abc123"}'
    redacted = redact_text(text)
    assert "abc123" not in redacted
    assert "svc-1" in redacted


def test_federation_provider_redacted_connection_settings_hides_secrets():
    provider = FederationProviderConfig(
        name="corp-ldap",
        provider_type=FederationProviderType.LDAP,
        connection_settings={
            "url": "ldaps://ldap.example.internal",
            "bind_password": "hunter2",
        },
    )
    redacted = provider.redacted_connection_settings()
    assert redacted["url"] == "ldaps://ldap.example.internal"
    assert redacted["bind_password"] == "***REDACTED***"
