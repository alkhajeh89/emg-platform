"""Knowledge Graph Query API configuration, loaded from environment.

Mirrors `emg_audit_service.config.Settings`'s shape and env-var-prefix
convention exactly (same inbound service-token trust path: RS256 tokens
verified against the realm JWKS). No secret has a hardcoded production
value; local-dev defaults match docker-compose.yml and are overridden
per-environment via env vars from the centralized secrets store.

`tenant_claim` names the JWT custom claim this service reads to resolve the
caller's tenant (see `authn.py`'s module docstring for why this claim is a
new, Sprint-7.4-only convention with no existing repository precedent).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMG_KNOWLEDGE_GRAPH_API_", env_file=".env", extra="ignore"
    )

    # Graph storage backend: "memory" (tests / local without a DB) or
    # "postgres" (PostgresNeo4jGraphStore, PostgreSQL-authoritative, Neo4j
    # projection left unwired here — ADR-024 §19 does not require it, and
    # this sprint's STRICT RULES forbid touching Neo4j).
    store_backend: str = "memory"

    # PostgreSQL connection (used only when store_backend == "postgres").
    postgres_dsn: str = (
        "postgresql://emg_knowledge_graph_app:emg_knowledge_graph_local_dev_only_do_not_use_in_prod"
        "@localhost:5432/emg"
    )
    postgres_connect_timeout_seconds: float = 10.0

    # Inbound service-token validation (same trust path as
    # services/audit/services/identity: RS256 tokens verified against the
    # realm JWKS).
    keycloak_base_url: str = "http://localhost:8080"
    keycloak_realm: str = "emg"
    service_token_audience: str = "emg-internal-services"
    jwks_cache_ttl_seconds: int = 300

    # The JWT custom claim carrying the caller's resolved tenant identifier
    # (Sprint 7.4 addition — see authn.py).
    tenant_claim: str = "tenant_id"

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    @property
    def jwks_uri(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"


def get_settings() -> Settings:
    return Settings()
