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

from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from emg_api_contracts import reject_unknown_environment
from pydantic_settings import BaseSettings, SettingsConfigDict

StoreBackend = Literal["memory", "postgres"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMG_KNOWLEDGE_GRAPH_API_", env_file=".env", extra="ignore"
    )

    # Graph storage backend: "memory" (tests / local without a DB) or
    # "postgres" (PostgresNeo4jGraphStore, PostgreSQL-authoritative, Neo4j
    # projection left unwired here — ADR-024 §19 does not require it, and
    # this sprint's STRICT RULES forbid touching Neo4j).
    store_backend: StoreBackend = "memory"

    # PostgreSQL connection (used only when store_backend == "postgres").
    postgres_dsn: str = (
        "postgresql://emg_knowledge_graph_app:emg_knowledge_graph_local_dev_only_do_not_use_in_prod"
        "@localhost:5432/emg"
    )
    migration_postgres_dsn: str = (
        "postgresql://emg_knowledge_graph_migrator:"
        "emg_knowledge_graph_migrator_local_dev_only_do_not_use_in_prod"
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

    # ADR-026 Revision 2 (Amendment 2, Group D5): the JWT custom claim
    # carrying a caller's classification clearance, extracted into
    # ServicePrincipal.attributes. Follows the exact same optional-claim
    # convention as tenant_claim above — except a missing claim is not an
    # authentication error (see authn.py's `_extract_attributes`).
    classification_clearance_claim: str = "classification_clearance"

    # --- ADR-025 Group C: Knowledge Graph Authorization Enforcement --------
    #
    # Path to the local ABAC policy configuration (emg_policy_engine.PolicyConfig).
    # Same safe-default posture as services/identity's policy_config_path: a
    # missing file falls back to an empty, default-deny ruleset (see
    # emg_policy_engine.loader.load_policy_config) rather than raising, so a
    # misconfigured deployment fails closed (denies everything) instead of
    # failing to start or silently allowing everything.
    policy_config_path: Path = Path("services/knowledge-graph/config/policy.example.yaml")

    # ADR-033 Revision 2: the externally supplied, version-controlled catalog
    # is loaded once during startup. Phase 2 deliberately supplies no default
    # artifact; Phase 3 owns shipping the first catalog.
    schema_catalog_path: Path | None = None
    # No default is deliberate: explicitly enabling the fail-closed placeholder
    # also requires an explicit, recognized non-production environment.
    deployment_environment: Literal["development", "test", "production"] | None = None
    allow_unconfigured_schema_negotiation: bool = False

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    @property
    def jwks_uri(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"


def get_settings() -> Settings:
    return Settings()


def validate_secure_transport(settings: Settings) -> None:
    """Reject plaintext external transports in production."""

    if settings.deployment_environment != "production":
        return
    reject_unknown_environment("EMG_KNOWLEDGE_GRAPH_API_", set(Settings.model_fields))
    if urlsplit(settings.keycloak_base_url).scheme != "https":
        raise RuntimeError("knowledge-graph production Keycloak transport must use HTTPS")
    for name, dsn in (
        ("runtime", settings.postgres_dsn),
        ("migration", settings.migration_postgres_dsn),
    ):
        sslmode = parse_qs(urlsplit(dsn).query).get("sslmode", [])
        if not sslmode or sslmode[-1] not in {"require", "verify-ca", "verify-full"}:
            raise RuntimeError(
                f"knowledge-graph production {name} PostgreSQL transport must require TLS"
            )
