"""Audit service configuration, loaded from environment.

No secret has a hardcoded production value; local-dev defaults match
docker-compose.yml and are overridden per-environment via env vars from the
centralized secrets store (Engineering Master Plan §5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from emg_api_contracts import reject_unknown_environment
from pydantic_settings import BaseSettings, SettingsConfigDict

StoreBackend = Literal["memory", "postgres"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMG_AUDIT_", env_file=".env", extra="ignore")

    # Storage backend: "memory" (tests / local without a DB) or "postgres".
    store_backend: StoreBackend = "memory"
    deployment_environment: Literal["development", "test", "production"] = "development"

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
    tenant_claim: str = "tenant_id"
    policy_config_path: Path = Path("services/audit/config/policy.example.yaml")

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    @property
    def jwks_uri(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"


def get_settings() -> Settings:
    return Settings()


def validate_runtime_configuration(settings: Settings) -> None:
    """Prevent volatile audit storage in production."""

    if settings.deployment_environment == "production" and settings.store_backend == "memory":
        raise RuntimeError("audit cannot start in production with the in-memory store backend")
    if settings.deployment_environment == "production":
        reject_unknown_environment("EMG_AUDIT_", set(Settings.model_fields))
        if urlsplit(settings.keycloak_base_url).scheme != "https":
            raise RuntimeError("audit production Keycloak transport must use HTTPS")
        sslmode = parse_qs(urlsplit(settings.postgres_dsn).query).get("sslmode", [])
        if not sslmode or sslmode[-1] not in {"require", "verify-ca", "verify-full"}:
            raise RuntimeError("audit production PostgreSQL transport must require TLS")
