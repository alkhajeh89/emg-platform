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
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_KEYCLOAK_CLIENT_SECRET = "emg_identity_local_dev_secret_do_not_use_in_prod"
DEFAULT_SESSION_SIGNING_KEY = "emg_local_dev_session_signing_key_do_not_use_in_prod"
DEFAULT_SERVICE_CLIENT_SECRET = "emg_svc_identity_local_dev_secret_do_not_use_in_prod"
MINIMUM_SESSION_SIGNING_KEY_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMG_IDENTITY_", env_file=".env", extra="ignore")

    # Keycloak (FEAT-02-1)
    keycloak_base_url: str = "http://localhost:8080"
    keycloak_realm: str = "emg"
    keycloak_client_id: str = "emg-identity-service"
    keycloak_client_secret: str = DEFAULT_KEYCLOAK_CLIENT_SECRET
    keycloak_request_timeout_seconds: float = 5.0

    # EMG session token (FEAT-02-2)
    # Symmetric (HS256) signing key for local development. Production
    # deployments MUST override via EMG_IDENTITY_SESSION_SIGNING_KEY sourced
    # from the centralized secrets store (Engineering Master Plan §5), never
    # committed to source control.
    session_signing_key: str = DEFAULT_SESSION_SIGNING_KEY
    session_signing_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900  # 15 minutes
    refresh_token_ttl_seconds: int = 43200  # 12 hours
    refresh_token_store_backend: Literal["memory", "postgres"] = "memory"
    refresh_token_postgres_dsn: str = (
        "postgresql://emg_identity_app:emg_identity_local_dev_only_do_not_use_in_prod"
        "@localhost:5432/emg"
    )
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
    service_client_secret: str = DEFAULT_SERVICE_CLIENT_SECRET
    deployment_environment: Literal["development", "test", "production"] = "development"

    # Inbound validation of OTHER services' machine tokens (ServiceTokenValidator).
    # Keycloak-issued service-account tokens are RS256, verified against the
    # realm's JWKS endpoint — a different trust path from the HS256 EMG
    # session tokens above, which is what gives FEAT-02-3's "clear
    # separation between user sessions and service identities" its real
    # cryptographic teeth (see service_token_validator.py).
    service_token_audience: str = "emg-internal-services"
    jwks_cache_ttl_seconds: int = 300

    # ADR-026 Revision 2 (Amendment 2, Group D5): the JWT custom claim
    # carrying a caller's classification clearance, extracted into
    # ServicePrincipal.attributes. Following the exact same optional-claim
    # convention services/knowledge-graph's authn.py first established for
    # tenant_claim — except a missing claim is not an authentication error
    # (see service_token_validator.py's `_extract_attributes`).
    classification_clearance_claim: str = "classification_clearance"
    tenant_claim: str = "tenant_id"

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

    # --- Sprint 4: Authorization Platform (FEAT-03-1, FEAT-03-2) -----------
    #
    # Path to the local ABAC policy configuration (emg_policy_engine.PolicyConfig).
    # Same safe-default posture as federation_config_path above: a missing
    # file falls back to an empty, default-deny ruleset (see
    # emg_policy_engine.loader.load_policy_config) rather than raising.
    policy_config_path: Path = Path("services/identity/config/policy.example.yaml")

    # --- Sprint 6: Audit Event Pipeline forwarding (FEAT-04-1) -------------
    #
    # The identity service forwards each governed-action audit event to the
    # audit service (Module 6). Decision C (Sprint 6): a transient audit
    # outage must NOT fail login/authentication — the PipelineAuditSink
    # delivers, then durably spools + retries + dead-letters on failure, and
    # never silently claims an unrecorded event. See audit_pipeline.py.
    # Forwarding is OFF by default so Sprint 2-5 behavior is preserved
    # byte-for-byte (telemetry-only, no network, no spool). It is enabled by
    # configuration once the audit service is present (e.g. docker-compose),
    # at which point the PipelineAuditSink's durable-delivery machinery
    # activates. Existing login/authentication endpoints never fail because
    # the audit service is unavailable (Decision C).
    audit_forwarding_enabled: bool = False
    audit_service_base_url: str = "http://localhost:8002"
    audit_delivery_timeout_seconds: float = 3.0
    audit_delivery_max_attempts: int = 5
    audit_delivery_backoff_base_seconds: float = 0.5
    # Durable local spool for events not yet accepted by the audit service.
    audit_spool_path: Path = Path("services/identity/.audit-spool")


def get_settings() -> Settings:
    """Factory (not a singleton) so tests can construct isolated Settings
    without relying on process-wide caching/mutable global state."""
    return Settings()


def validate_runtime_configuration(settings: Settings) -> None:
    """Reject development credentials and unsafe audit settings in production."""

    if settings.deployment_environment != "production":
        return

    signing_key = settings.session_signing_key
    if not signing_key.strip():
        raise RuntimeError("identity production session signing key must not be blank")
    if len(signing_key.encode("utf-8")) < MINIMUM_SESSION_SIGNING_KEY_BYTES:
        raise RuntimeError(
            "identity production session signing key does not meet the minimum strength"
        )
    if signing_key == DEFAULT_SESSION_SIGNING_KEY:
        raise RuntimeError("identity production session signing key uses a development credential")

    development_credentials = (
        (settings.keycloak_client_secret, DEFAULT_KEYCLOAK_CLIENT_SECRET),
        (settings.service_client_secret, DEFAULT_SERVICE_CLIENT_SECRET),
    )
    if any(not value.strip() or value == default for value, default in development_credentials):
        raise RuntimeError("identity production configuration contains a development credential")
    if not settings.audit_forwarding_enabled:
        raise RuntimeError("identity production configuration requires durable audit forwarding")
    if settings.refresh_token_store_backend != "postgres":
        raise RuntimeError("identity production configuration requires durable refresh-token state")
