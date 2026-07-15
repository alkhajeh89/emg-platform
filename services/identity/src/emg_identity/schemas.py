"""Request/response models for the identity service's HTTP surface.

Kept as plain pydantic models local to this service rather than added to
emg_api_contracts (Sprint 1): these are identity-specific payload shapes,
not a cross-cutting envelope convention. The response envelope itself
(ApiResponse/ApiError) is reused from emg_api_contracts in main.py's
exception handling.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class SessionInfoResponse(BaseModel):
    subject: str
    roles: list[str]
    attributes: dict[str, str]


# --- Sprint 3: Service Identity & M2M Authentication (FEAT-02-3) ----------


class ServiceSessionInfoResponse(BaseModel):
    client_id: str
    service_name: str
    roles: list[str]
    scopes: list[str]


# --- Sprint 3: Identity Federation Readiness (FEAT-02-4) -------------------


class FederationProviderSummary(BaseModel):
    """Redacted view of a configured federation provider — never includes
    `connection_settings` values that look secret (see redact.py)."""

    name: str
    provider_type: str
    enabled: bool
    display_name: str
    connection_settings: dict[str, object]


class FederationProvidersResponse(BaseModel):
    local_fallback_enabled: bool
    providers: list[FederationProviderSummary]


class FederationHealthResponse(BaseModel):
    valid: bool
    problems: list[str]
    provider_count: int
    enabled_provider_count: int
    local_fallback_enabled: bool


# --- Sprint 4: Authorization Platform (FEAT-03-1, FEAT-03-2) ---------------


class PolicyCheckResponse(BaseModel):
    """Reference/introspection response for `GET /authz/check` — see that
    router's module docstring for why this endpoint always returns 200 with
    the Decision in the body rather than mapping deny to an HTTP error."""

    subject: str
    resource_type: str
    action: str
    outcome: str
    allowed: bool
    reason: str
    policy_id: str | None
