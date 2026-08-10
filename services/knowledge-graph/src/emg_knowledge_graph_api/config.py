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

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from emg_api_contracts import reject_unknown_environment
from emg_knowledge_graph_infrastructure import SchemaCatalogValidationError
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

StoreBackend = Literal["memory", "postgres"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMG_KNOWLEDGE_GRAPH_API_", env_file=".env", extra="ignore"
    )

    # Graph storage backend: "memory" (tests / local without a DB) or
    # "postgres" (PostgresNeo4jGraphStore, PostgreSQL-authoritative, with the
    # optional Neo4j serving projection configured below).
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
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 10

    # Optional Neo4j serving projection. PostgreSQL remains authoritative.
    neo4j_uri: str | None = None
    neo4j_user: str | None = None
    neo4j_password: SecretStr | None = None
    neo4j_max_pool_size: int = 10

    # Inbound service-token validation (same trust path as
    # services/audit/services/identity: RS256 tokens verified against the
    # realm JWKS).
    keycloak_base_url: str = "http://localhost:8080"
    keycloak_realm: str = "emg"
    service_token_audience: str = "emg-internal-services"
    jwks_cache_ttl_seconds: int = 300
    readiness_timeout_seconds: float = 2.0

    # The JWT custom claim carrying the caller's resolved tenant identifier
    # (Sprint 7.4 addition — see authn.py).
    tenant_claim: str = "tenant_id"

    # Phase 2B (ADR-038 Ch. VII §7.4 Audience Restriction): the single
    # downstream audience identifier a Delegated Credential must carry to be
    # accepted by DelegatedCredentialValidator. A credential issued for any
    # other audience is rejected — this service is never a generic,
    # multi-audience acceptor.
    delegated_credential_audience: str = "emg-knowledge-graph-audience"

    # Phase 2B (ADR-038 §8.7 Audit Attribution): this service's OWN outbound
    # service-to-service credential, used ONLY to authenticate its own
    # audit-producer calls for delegated (human-attributed) requests — an
    # ordinary ADR-034 service-to-service call, not part of the delegation
    # chain itself. Reuses the already-registered, already-recognized
    # `emg-svc-knowledge-graph-writer` client (see
    # tools/seed-data/keycloak/emg-realm.json and
    # emg_audit_service.authn._RECOGNIZED_CLIENTS) rather than registering a
    # new client identity.
    audit_producer_client_id: str = "emg-svc-knowledge-graph-writer"
    audit_producer_client_secret: SecretStr = SecretStr(
        "emg_svc_knowledge_graph_writer_local_dev_secret_do_not_use_in_prod"
    )
    audit_producer_audience: str = "emg-internal-services"
    audit_service_base_url: str = "http://localhost:8002"

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

    # ADR-042 approved implementation profile.
    search_cursor_default_ttl_seconds: int = 900
    search_cursor_max_ttl_seconds: int = 1800
    search_representation_retention_seconds: int = 3600
    search_cleanup_interval_seconds: int = 900
    search_cleanup_batch_size: int = 500
    search_candidate_batch_size: int = 200
    search_candidate_work_ceiling: int = 10_000
    search_cursor_active_key_id: str = "development"
    search_cursor_keys_json: SecretStr = SecretStr(
        '{"development":"ZGV2ZWxvcG1lbnQtb25seS1rZXktMzItYnl0ZXMhISE="}'
    )

    @model_validator(mode="after")
    def _search_profile_valid(self) -> Settings:
        if not (
            0
            < self.search_cursor_default_ttl_seconds
            <= self.search_cursor_max_ttl_seconds
            <= self.search_representation_retention_seconds
        ):
            raise ValueError(
                "search cursor TTL must be positive and no longer than representation retention"
            )
        if self.search_cleanup_interval_seconds <= 0:
            raise ValueError("search cleanup interval must be positive")
        if not 1 <= self.search_cleanup_batch_size <= 5_000:
            raise ValueError("search cleanup batch size must be in [1, 5000]")
        if not 1 <= self.search_candidate_batch_size <= 1_000 or not (
            self.search_candidate_batch_size <= self.search_candidate_work_ceiling <= 10_000
        ):
            raise ValueError("invalid governed-search candidate work configuration")
        search_cursor_keys(self)
        return self

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    @property
    def jwks_uri(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"

    @property
    def token_endpoint(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/token"


def get_settings() -> Settings:
    return Settings()


def search_cursor_keys(settings: Settings, *, now: datetime | None = None) -> dict[str, bytes]:
    """Decode keys whose governed acceptance windows have not ended.

    An active-only string value remains a compact local-development form.
    Every prior key requires explicit retirement metadata; there is no
    revision-count-like key limit that can evict a still-required key.
    """
    try:
        raw = json.loads(settings.search_cursor_keys_json.get_secret_value())
        if not isinstance(raw, dict) or not raw:
            raise ValueError
        current = now or datetime.now(timezone.utc)
        keys: dict[str, bytes] = {}
        active_entries = 0
        for key_id, entry in raw.items():
            if not isinstance(key_id, str) or not key_id or len(key_id) > 64:
                raise ValueError
            if isinstance(entry, str):
                if key_id != settings.search_cursor_active_key_id:
                    raise ValueError
                active_entries += 1
                keys[key_id] = _decode_cursor_key(entry)
                continue
            if not isinstance(entry, dict) or set(entry) - {
                "key",
                "status",
                "retired_at",
                "accept_until",
            }:
                raise ValueError
            status = entry.get("status")
            if status == "active":
                if key_id != settings.search_cursor_active_key_id:
                    raise ValueError
                active_entries += 1
                keys[key_id] = _decode_cursor_key(entry.get("key"))
                if entry.get("retired_at") is not None or entry.get("accept_until") is not None:
                    raise ValueError
                continue
            if status not in {"retired", "disabled"}:
                raise ValueError
            retired_at = _parse_cursor_key_time(entry.get("retired_at"))
            accept_until = _parse_cursor_key_time(entry.get("accept_until"))
            if retired_at > current or accept_until < retired_at + timedelta(
                seconds=settings.search_representation_retention_seconds
            ):
                raise ValueError
            if accept_until > current:
                if status != "retired":
                    raise ValueError
                keys[key_id] = _decode_cursor_key(entry.get("key"))
            elif entry.get("key") is not None:
                _decode_cursor_key(entry.get("key"))
        if active_entries != 1 or settings.search_cursor_active_key_id not in keys:
            raise ValueError
        return keys
    except Exception as exc:
        raise ValueError("invalid governed-search cursor key-ring configuration") from exc


def _decode_cursor_key(encoded: object) -> bytes:
    if not isinstance(encoded, str):
        raise ValueError
    key = base64.b64decode(encoded, validate=True)
    if len(key) != 32:
        raise ValueError
    return key


def _parse_cursor_key_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed.astimezone(timezone.utc)


_DEV_PLACEHOLDER_AUDIT_PRODUCER_SECRET = (
    "emg_svc_knowledge_graph_writer_local_dev_secret_do_not_use_in_prod"
)
_DEV_RUNTIME_POSTGRES_PASSWORD = "emg_knowledge_graph_local_dev_only_do_not_use_in_prod"
_DEV_MIGRATION_POSTGRES_PASSWORD = "emg_knowledge_graph_migrator_local_dev_only_do_not_use_in_prod"
_DEV_NEO4J_PASSWORD = "emg_local_dev_only"


def validate_secure_transport(settings: Settings) -> None:
    """Reject plaintext external transports in production.

    **Final correction-sprint Finding 5.** Also reject the known, committed
    dev-placeholder audit-producer client secret — see the equivalent check
    in `apps/studio-bff/.../config.py::validate_runtime_configuration` for
    the identical rationale."""

    if settings.deployment_environment != "production":
        return
    reject_unknown_environment("EMG_KNOWLEDGE_GRAPH_API_", set(Settings.model_fields))
    if urlsplit(settings.keycloak_base_url).scheme != "https":
        raise RuntimeError("knowledge-graph production Keycloak transport must use HTTPS")
    if urlsplit(settings.audit_service_base_url).scheme != "https":
        # Correction-sprint Finding 11: this check was missing even though
        # Phase 2B introduced a new outbound production dependency
        # (delegated-request audit attribution, audit_producer.py) with the
        # same transport-security requirement as every other external call
        # this function already guards.
        raise RuntimeError("knowledge-graph production audit-service transport must use HTTPS")
    for name, dsn, development_password in (
        ("runtime", settings.postgres_dsn, _DEV_RUNTIME_POSTGRES_PASSWORD),
    ):
        parsed_dsn = urlsplit(dsn)
        sslmode = parse_qs(parsed_dsn.query).get("sslmode", [])
        if not sslmode or sslmode[-1] not in {"require", "verify-ca", "verify-full"}:
            raise RuntimeError(
                f"knowledge-graph production {name} PostgreSQL transport must require TLS"
            )
        if not parsed_dsn.password or parsed_dsn.password == development_password:
            raise RuntimeError(
                f"knowledge-graph production {name} PostgreSQL credential is blank or uses "
                "a development value"
            )
    audit_secret = settings.audit_producer_client_secret.get_secret_value()
    if not audit_secret or audit_secret == _DEV_PLACEHOLDER_AUDIT_PRODUCER_SECRET:
        raise RuntimeError(
            "knowledge-graph production audit_producer_client_secret is still the committed "
            "dev placeholder"
        )
    if settings.neo4j_uri is not None:
        if urlsplit(settings.neo4j_uri).scheme != "neo4j+s":
            raise RuntimeError("knowledge-graph production Neo4j transport must use neo4j+s")
        if not settings.neo4j_user or settings.neo4j_password is None:
            raise RuntimeError("knowledge-graph production Neo4j credentials are required")
        neo4j_password = settings.neo4j_password.get_secret_value()
        if not neo4j_password or neo4j_password == _DEV_NEO4J_PASSWORD:
            raise RuntimeError(
                "knowledge-graph production Neo4j credential is blank or uses a development value"
            )
    if not settings.policy_config_path.is_file():
        raise RuntimeError("knowledge-graph production policy configuration file is missing")
    if settings.schema_catalog_path is None or not settings.schema_catalog_path.is_file():
        raise SchemaCatalogValidationError(
            "knowledge-graph production schema catalog file is missing"
        )
    if settings.search_cursor_active_key_id == "development":
        raise RuntimeError("knowledge-graph production search cursor key is a development key")


def validate_migration_configuration(settings: Settings) -> None:
    """Validate the owner credential in the migration process, never the server."""
    if settings.deployment_environment != "production":
        return
    parsed_dsn = urlsplit(settings.migration_postgres_dsn)
    sslmode = parse_qs(parsed_dsn.query).get("sslmode", [])
    if not sslmode or sslmode[-1] not in {"require", "verify-ca", "verify-full"}:
        raise RuntimeError(
            "knowledge-graph production migration PostgreSQL transport must require TLS"
        )
    if not parsed_dsn.password or parsed_dsn.password == _DEV_MIGRATION_POSTGRES_PASSWORD:
        raise RuntimeError(
            "knowledge-graph production migration PostgreSQL credential is blank or uses "
            "a development value"
        )
    if settings.migration_postgres_dsn == settings.postgres_dsn:
        raise RuntimeError(
            "knowledge-graph production runtime and migration database credentials must be distinct"
        )
