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
