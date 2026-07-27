"""Audit service configuration, loaded from environment.

No secret has a hardcoded production value; local-dev defaults match
docker-compose.yml and are overridden per-environment via env vars from the
centralized secrets store (Engineering Master Plan §5).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMG_AUDIT_", env_file=".env", extra="ignore")

    # Storage backend: "memory" (tests / local without a DB) or "postgres".
    store_backend: str = "memory"

    # PostgreSQL connection (used only when store_backend == "postgres").
    # Local-dev default matches docker-compose.yml's emg_audit_app role created
    # by tools/seed-data/postgres/001_audit_events.sql.
    postgres_dsn: str = (
        "postgresql://emg_audit_app:emg_audit_local_dev_only_do_not_use_in_prod"
        "@localhost:5432/emg"
    )

    # Inbound service-token validation (same trust path as Sprint 3's identity
    # ServiceTokenValidator: RS256 tokens verified against the realm JWKS).
    keycloak_base_url: str = "http://localhost:8080"
    keycloak_realm: str = "emg"
    service_token_audience: str = "emg-internal-services"
    jwks_cache_ttl_seconds: int = 300

    # ADR-026 Revision 2 (Amendment 2, Group D5): the JWT custom claim
    # carrying a caller's classification clearance, extracted into
    # ServicePrincipal.attributes. Following the exact same optional-claim
    # convention services/knowledge-graph's authn.py first established for
    # tenant_claim — except a missing claim is not an authentication error
    # (see authn.py's `_extract_attributes`).
    classification_clearance_claim: str = "classification_clearance"

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    @property
    def jwks_uri(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"


def get_settings() -> Settings:
    return Settings()
