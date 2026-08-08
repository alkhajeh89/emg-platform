"""Studio BFF configuration, loaded from environment.

Mirrors every other service's `Settings` shape and env-var-prefix convention
(`services/knowledge-graph/.../config.py`, `services/audit/.../config.py`):
no secret has a hardcoded production value; the local-dev defaults below
match `tools/seed-data/keycloak/emg-realm.json` and `docker-compose.yml`,
overridden per-environment via the centralized secrets store.

**Token/session lifetime (Phase 2B Required Change #3):** `session_ttl_seconds`
below is an explicit, configurable value with a short development/test
default. It is deliberately NOT presented as a production standard — see
`docs/security/adr-038/07_PRODUCTION_CONFIGURATION.md`, which records the
production number as an undetermined deployment/security-baseline decision.
Nothing in this module, or anywhere else in this batch, hardcodes a
production figure.

**Correction-sprint Finding 4.** `session_absolute_ttl_seconds` is a second,
independent bound distinct from the access-token-tied idle expiry
(`session_ttl_seconds` governs how long an *unrefreshed* session cookie
lives; the absolute cap below governs how long a session may live at all,
refreshed or not) — ADR-035 D-8 requires "idle timeout and absolute lifetime
both bounded," two distinct bounds, not one reused as both.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from emg_api_contracts import reject_unknown_environment
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMG_STUDIO_BFF_", env_file=".env", extra="ignore")

    deployment_environment: Literal["development", "test", "production"] = "development"

    # --- Keycloak / OIDC (ADR-035) ------------------------------------
    keycloak_base_url: str = "http://localhost:8080"
    keycloak_realm: str = "emg"
    jwks_cache_ttl_seconds: int = 300

    # This BFF's own confidential OIDC client (ADR-035 D-3).
    oidc_client_id: str = "emg-studio-bff"
    oidc_client_secret: SecretStr = SecretStr("emg_studio_bff_local_dev_secret_do_not_use_in_prod")
    oidc_redirect_uri: str = "http://localhost:8010/auth/callback"
    oidc_scope: str = "openid"
    # ADR-035 D-1: PKCE S256 is the only permitted code-challenge method.
    pkce_code_challenge_method: Literal["S256"] = "S256"

    # Studio frontend location the BFF redirects back to after a successful
    # login (never a client-supplied redirect target — ADR-036 open-redirect
    # requirement; this is a fixed, server-configured value).
    studio_frontend_url: str = "http://localhost:3000"

    # --- Delegation (ADR-038) ------------------------------------------
    # Every recognized downstream audience this BFF is permitted to request
    # a Delegated Credential for. Phase 2B: Knowledge Graph only.
    knowledge_graph_audience: str = "emg-knowledge-graph-audience"
    knowledge_graph_base_url: str = "http://localhost:8003"
    readiness_timeout_seconds: float = 2.0

    tenant_claim: str = "tenant_id"
    classification_clearance_claim: str = "classification_clearance"

    # --- Server-side session (ADR-035 D-8) ------------------------------
    session_cookie_name: str = "__Host-emg_studio_session"
    csrf_cookie_name: str = "__Host-emg_studio_csrf"
    # Explicit, configurable, short development/test default — see module
    # docstring. NOT a production recommendation.
    session_ttl_seconds: int = 300
    # Correction-sprint Finding 4: independent absolute cap. A session is
    # deleted once `created_at + session_absolute_ttl_seconds` passes,
    # regardless of how recently it was refreshed.
    session_absolute_ttl_seconds: int = 3600
    # Correction-sprint Finding 5: how far before access-token expiry
    # `current_session_dependency` attempts a server-side refresh.
    session_refresh_margin_seconds: int = 60
    pre_auth_cookie_name: str = "__Host-emg_studio_preauth"
    pre_auth_ttl_seconds: int = 300

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"

    @property
    def jwks_uri(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/certs"

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/auth"

    @property
    def token_endpoint(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/token"

    @property
    def end_session_endpoint(self) -> str:
        return f"{self.keycloak_issuer}/protocol/openid-connect/logout"


def get_settings() -> Settings:
    return Settings()


_DEV_PLACEHOLDER_OIDC_CLIENT_SECRET = "emg_studio_bff_local_dev_secret_do_not_use_in_prod"


def validate_runtime_configuration(settings: Settings) -> None:
    """Reject plaintext external transports and volatile session storage in
    production (same posture as every other service's `validate_*_transport`).

    **Final correction-sprint Finding 5.** Also reject the known, committed
    dev-placeholder OIDC client secret — production startup previously
    succeeded even with the literal dev secret from
    `tools/seed-data/keycloak/emg-realm.json` still configured, which would
    silently run production against a value anyone with repository access
    already knows."""

    if settings.deployment_environment != "production":
        return
    reject_unknown_environment("EMG_STUDIO_BFF_", set(Settings.model_fields))
    oidc_secret = settings.oidc_client_secret.get_secret_value()
    if not oidc_secret or oidc_secret == _DEV_PLACEHOLDER_OIDC_CLIENT_SECRET:
        raise RuntimeError(
            "studio-bff production oidc_client_secret is still the committed dev placeholder"
        )
    if urlsplit(settings.keycloak_base_url).scheme != "https":
        raise RuntimeError("studio-bff production Keycloak transport must use HTTPS")
    if urlsplit(settings.knowledge_graph_base_url).scheme != "https":
        raise RuntimeError("studio-bff production Knowledge Graph transport must use HTTPS")
    if not settings.oidc_redirect_uri.startswith("https://"):
        raise RuntimeError("studio-bff production redirect_uri must use HTTPS")
    if urlsplit(settings.studio_frontend_url).scheme != "https":
        raise RuntimeError("studio-bff production frontend URL must use HTTPS")
    for name, value in (
        ("session_cookie_name", settings.session_cookie_name),
        ("csrf_cookie_name", settings.csrf_cookie_name),
        ("pre_auth_cookie_name", settings.pre_auth_cookie_name),
    ):
        if not value.startswith("__Host-"):
            raise RuntimeError(f"studio-bff production {name} must use the __Host- prefix")
    if settings.session_ttl_seconds <= 0 or settings.session_absolute_ttl_seconds <= 0:
        raise RuntimeError("studio-bff production session lifetimes must be positive")
    if settings.session_ttl_seconds > settings.session_absolute_ttl_seconds:
        raise RuntimeError("studio-bff session TTL cannot exceed its absolute lifetime")
