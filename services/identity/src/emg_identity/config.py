"""Service configuration, loaded from environment (.env at repo root).

No secret has a hardcoded production value; local-dev defaults below match
docker-compose.yml / tools/seed-data/keycloak/emg-realm.json exactly and are
overridden per-environment via env vars in real deployments (Engineering
Master Plan §5: secrets are "never embedded in images or configuration
files" — the defaults here are local-development-only and documented as
such).

Sprint 3 (FEAT-02-3, FEAT-02-4) additions are grouped below the Sprint 1/2
settings; no Sprint 1/2 field was renamed, retyped, or removed, so existing
deployments' environment variables keep working unchanged.
"""

from __future__ import annotations

from pathlib import Path

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

    # --- Sprint 3: Service Identity & M2M Authentication (FEAT-02-3) -------
    #
    # This service's OWN outbound service-account credentials (used when the
    # identity service itself needs to call another EMG service as a
    # machine, not on behalf of a human). Every other service is expected to
    # hold only its own client_id/secret the same way — never a shared or
    # centrally-brokered secret (see services/identity/README.md, "Why the
    # identity service does not broker M2M tokens").
    service_client_id: str = "emg-svc-identity"
    service_client_secret: str = "emg_svc_identity_local_dev_secret_do_not_use_in_prod"

    # Inbound validation of OTHER services' machine tokens (ServiceTokenValidator).
    # Keycloak-issued service-account tokens are RS256, verified against the
    # realm's JWKS endpoint — a different trust path from the HS256 EMG
    # session tokens above, which is what gives FEAT-02-3's "clear
    # separation between user sessions and service identities" its real
    # cryptographic teeth (see service_token_validator.py).
    service_token_audience: str = "emg-internal-services"
    jwks_cache_ttl_seconds: int = 300

    @property
    def keycloak_issuer(self) -> str:
        """Expected `iss` claim on any Keycloak-issued token (human or
        machine): `{base_url}/realms/{realm}`, per OIDC discovery
        convention. Computed, not stored, so it can never drift from
        keycloak_base_url/keycloak_realm."""
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    @property
    def jwks_uri(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"

    # --- Sprint 3: Identity Federation Readiness (FEAT-02-4) ---------------
    #
    # Path to the federation configuration file (FederationConfig, see
    # federation.py). Missing-file handling is deliberately graceful (falls
    # back to local-only) — see federation.py's `load_federation_config`.
    federation_config_path: Path = Path("services/identity/config/federation.example.yaml")

    # --- Sprint 3: rate-limiting readiness (Required Security Controls) ----
    #
    # Applied to /auth/login only this sprint (the human credential-guessing
    # attack surface). Basic in-memory, single-process limiter — explicitly
    # "readiness," not a production control; see rate_limit.py.
    login_rate_limit_max_attempts: int = 10
    login_rate_limit_window_seconds: float = 60.0


def get_settings() -> Settings:
    """Factory (not a singleton) so tests can construct isolated Settings
    without relying on process-wide caching/mutable global state."""
    return Settings()
