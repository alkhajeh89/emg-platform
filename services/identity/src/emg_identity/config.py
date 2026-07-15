"""Service configuration, loaded from environment (.env at repo root).

No secret has a hardcoded production value; local-dev defaults below match
docker-compose.yml / tools/seed-data/keycloak/emg-realm.json exactly and are
overridden per-environment via env vars in real deployments (Engineering
Master Plan §5: secrets are "never embedded in images or configuration
files" — the defaults here are local-development-only and documented as
such).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMG_IDENTITY_", env_file=".env", extra="ignore")

    # Keycloak (FEAT-02-1)
    keycloak_base_url: str = "http://localhost:8080"
    keycloak_realm: str = "emg"
    keycloak_client_id: str = "emg-identity-service"
    keycloak_client_secret: str = "emg_identity_local_dev_secret_do_not_use_in_prod"
    keycloak_request_timeout_seconds: float = 5.0

    # EMG session token (FEAT-02-2)
    # Symmetric (HS256) signing key for local development. Production
    # deployments MUST override via EMG_IDENTITY_SESSION_SIGNING_KEY sourced
    # from the centralized secrets store (Engineering Master Plan §5), never
    # committed to source control.
    session_signing_key: str = "emg_local_dev_session_signing_key_do_not_use_in_prod"
    session_signing_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900        # 15 minutes
    refresh_token_ttl_seconds: int = 43200      # 12 hours
    token_issuer: str = "emg-identity-service"
    token_audience: str = "emg-platform"


def get_settings() -> Settings:
    """Factory (not a singleton) so tests can construct isolated Settings
    without relying on process-wide caching/mutable global state."""
    return Settings()
