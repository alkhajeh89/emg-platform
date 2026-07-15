"""Federation readiness tests (FEAT-02-4).

Covers: safe handling of missing federation configuration, loading the
committed example config, configuration validation (valid and invalid
shapes), and claim/group-role mapping projection. No test in this file
contacts an external directory or network resource — that is the point of
"readiness" (see federation.py's module docstring).
"""

from __future__ import annotations

from pathlib import Path

from emg_identity.federation import (
    ClaimMapping,
    FederationConfig,
    FederationProviderConfig,
    FederationProviderType,
    GroupRoleMapping,
    apply_claim_mappings,
    apply_group_role_mappings,
    default_federation_config,
    load_federation_config,
    validate_federation_config,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLE_CONFIG_PATH = _REPO_ROOT / "services/identity/config/federation.example.yaml"


def test_default_federation_config_is_local_only():
    config = default_federation_config()
    assert config.providers == []
    assert config.local_fallback_enabled is True


def test_load_federation_config_missing_file_falls_back_to_default(tmp_path):
    """Testing Requirement: "Safe handling of missing federation
    configuration" — must never raise."""
    missing_path = tmp_path / "does-not-exist.yaml"
    config = load_federation_config(missing_path)
    assert config == default_federation_config()


def test_load_federation_config_reads_committed_example_file():
    assert _EXAMPLE_CONFIG_PATH.exists(), "example federation config was not found"
    config = load_federation_config(_EXAMPLE_CONFIG_PATH)
    assert len(config.providers) >= 1
    assert all(not provider.enabled for provider in config.providers)
    assert config.local_fallback_enabled is True
    assert validate_federation_config(config) == []


def test_validate_default_config_has_no_problems():
    assert validate_federation_config(default_federation_config()) == []


def test_validate_rejects_enabled_provider_without_connection_settings():
    config = FederationConfig(
        providers=[
            FederationProviderConfig(
                name="corp-ldap",
                provider_type=FederationProviderType.LDAP,
                enabled=True,
            )
        ]
    )
    problems = validate_federation_config(config)
    assert any("connection_settings" in problem for problem in problems)


def test_validate_accepts_enabled_provider_with_connection_settings():
    config = FederationConfig(
        providers=[
            FederationProviderConfig(
                name="corp-ldap",
                provider_type=FederationProviderType.LDAP,
                enabled=True,
                connection_settings={"url": "ldaps://ldap.example.internal"},
            )
        ]
    )
    assert validate_federation_config(config) == []


def test_validate_rejects_duplicate_provider_names():
    provider = FederationProviderConfig(
        name="dup", provider_type=FederationProviderType.LOCAL, enabled=False
    )
    config = FederationConfig(providers=[provider, provider])
    problems = validate_federation_config(config)
    assert any("Duplicate provider name" in problem for problem in problems)


def test_validate_rejects_no_fallback_and_no_enabled_provider():
    config = FederationConfig(providers=[], local_fallback_enabled=False)
    problems = validate_federation_config(config)
    assert any("no authentication path would be available" in problem for problem in problems)


def test_validate_rejects_incomplete_claim_mapping():
    config = FederationConfig(
        providers=[
            FederationProviderConfig(
                name="ext-oidc",
                provider_type=FederationProviderType.OIDC_EXTERNAL,
                enabled=True,
                connection_settings={"discovery_url": "https://idp.example.internal/.well-known"},
                claim_mappings=[ClaimMapping(external_claim="", emg_attribute="department")],
            )
        ]
    )
    problems = validate_federation_config(config)
    assert any("incomplete claim mapping" in problem for problem in problems)


def test_validate_rejects_incomplete_group_role_mapping():
    config = FederationConfig(
        providers=[
            FederationProviderConfig(
                name="corp-ad",
                provider_type=FederationProviderType.ACTIVE_DIRECTORY,
                enabled=True,
                connection_settings={"url": "ldaps://ad.example.internal"},
                group_role_mappings=[GroupRoleMapping(external_group="Investigators", emg_role="")],
            )
        ]
    )
    problems = validate_federation_config(config)
    assert any("incomplete group-role mapping" in problem for problem in problems)


def test_apply_claim_mappings_projects_only_mapped_claims():
    provider = FederationProviderConfig(
        name="ext-oidc",
        provider_type=FederationProviderType.OIDC_EXTERNAL,
        claim_mappings=[
            ClaimMapping(external_claim="clearance", emg_attribute="classification_clearance"),
            ClaimMapping(external_claim="dept", emg_attribute="department"),
        ],
    )
    external_claims = {"clearance": "SECRET", "dept": "Investigations", "unmapped": "ignored-me"}

    attributes = apply_claim_mappings(provider, external_claims)

    assert attributes == {
        "classification_clearance": "SECRET",
        "department": "Investigations",
    }


def test_apply_claim_mappings_ignores_claims_not_present_in_source():
    provider = FederationProviderConfig(
        name="ext-oidc",
        provider_type=FederationProviderType.OIDC_EXTERNAL,
        claim_mappings=[ClaimMapping(external_claim="missing", emg_attribute="department")],
    )
    assert apply_claim_mappings(provider, {}) == {}


def test_apply_group_role_mappings_projects_matched_groups_only():
    provider = FederationProviderConfig(
        name="corp-ad",
        provider_type=FederationProviderType.ACTIVE_DIRECTORY,
        group_role_mappings=[
            GroupRoleMapping(external_group="Investigators", emg_role="investigator"),
            GroupRoleMapping(external_group="Platform-Users", emg_role="platform-user"),
        ],
    )
    roles = apply_group_role_mappings(provider, ["Investigators", "Some-Unmapped-Group"])
    assert roles == ("investigator",)
