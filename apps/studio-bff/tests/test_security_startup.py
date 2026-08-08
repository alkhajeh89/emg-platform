"""Production startup validation — final correction-sprint Finding 5.

Mirrors `services/knowledge-graph/tests/api/test_security_startup.py`'s
pattern: production startup must fail fast on plaintext transports and on
the committed dev-placeholder OIDC client secret."""

from __future__ import annotations

import pytest
from emg_studio_bff.config import Settings, validate_runtime_configuration


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "deployment_environment": "production",
        "keycloak_base_url": "https://keycloak.example.gov",
        "knowledge_graph_base_url": "https://knowledge-graph.example.gov",
        "oidc_redirect_uri": "https://studio.example.gov/auth/callback",
        "studio_frontend_url": "https://studio.example.gov",
        "oidc_client_secret": "a-real-production-secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_dev_placeholder_oidc_client_secret() -> None:
    settings = _production_settings(
        oidc_client_secret="emg_studio_bff_local_dev_secret_do_not_use_in_prod"
    )
    with pytest.raises(RuntimeError, match="dev placeholder"):
        validate_runtime_configuration(settings)


def test_production_accepts_non_placeholder_oidc_client_secret() -> None:
    validate_runtime_configuration(_production_settings())  # must not raise


@pytest.mark.parametrize(
    "overrides",
    [
        {"keycloak_base_url": "http://keycloak.example.gov"},
        {"knowledge_graph_base_url": "http://knowledge-graph.example.gov"},
        {"oidc_redirect_uri": "http://studio.example.gov/auth/callback"},
    ],
)
def test_production_rejects_plaintext_transport(overrides: dict[str, object]) -> None:
    settings = _production_settings(**overrides)
    with pytest.raises(RuntimeError, match="HTTPS"):
        validate_runtime_configuration(settings)


def test_development_environment_skips_all_checks() -> None:
    """The dev-placeholder secret and plaintext transports are expected —
    and fine — outside production."""
    settings = Settings(deployment_environment="development")
    validate_runtime_configuration(settings)  # must not raise
