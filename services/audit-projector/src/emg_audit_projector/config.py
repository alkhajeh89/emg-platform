"""Validated, tenant-explicit configuration for the Audit Projector."""

from __future__ import annotations

import json
from functools import cached_property
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from emg_common_types import (
    parse_projector_identity_inventory,
    validate_projector_credential_bindings,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TenantCredential(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: SecretStr

    @model_validator(mode="after")
    def reject_blank_secret(self) -> TenantCredential:
        if not self.client_secret.get_secret_value():
            raise ValueError("projector client secret must not be blank")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMG_AUDIT_PROJECTOR_",
        env_file=".env",
        extra="ignore",
    )

    deployment_environment: Literal["development", "test", "production"] = "development"
    postgres_dsn: str = "postgresql://emg_audit_projector@localhost:5432/emg"
    postgres_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    postgres_pool_min_size: int = Field(default=1, ge=0)
    postgres_pool_max_size: int = Field(default=4, ge=1)

    keycloak_base_url: str = "http://localhost:8080"
    keycloak_realm: str = "emg"
    token_audience: str = "emg-internal-services"
    audit_service_base_url: str = "http://localhost:8002"
    identity_inventory_json: str = ""
    tenant_credentials_json: SecretStr = SecretStr("[]")

    worker_id: str = Field(default="audit-projector-1", min_length=1)
    batch_size: int = Field(default=1, ge=1, le=100)
    poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    lease_seconds: float = Field(default=30.0, gt=0, le=300)
    drain_timeout_seconds: float = Field(default=20.0, gt=0, le=300)
    http_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    max_attempts: int = Field(default=8, ge=1, le=8)
    telemetry_interval_seconds: float = Field(default=30.0, gt=0, le=300)

    @property
    def token_endpoint(self) -> str:
        return (
            f"{self.keycloak_base_url}/realms/{self.keycloak_realm}"
            "/protocol/openid-connect/token"
        )

    @cached_property
    def tenant_credentials(self) -> tuple[TenantCredential, ...]:
        try:
            raw = json.loads(self.tenant_credentials_json.get_secret_value())
        except json.JSONDecodeError as exc:
            raise ValueError("tenant_credentials_json must be valid JSON") from exc
        if not isinstance(raw, list):
            raise ValueError("tenant_credentials_json must contain a JSON array")
        credentials = tuple(TenantCredential.model_validate(item) for item in raw)
        tenants = [credential.tenant_id for credential in credentials]
        clients = [credential.client_id for credential in credentials]
        if len(set(tenants)) != len(tenants):
            raise ValueError("projector tenant credentials must contain unique tenants")
        if len(set(clients)) != len(clients):
            raise ValueError("each projector tenant must use a distinct logical client identity")
        return credentials

    @model_validator(mode="after")
    def validate_runtime_bounds(self) -> Settings:
        if self.postgres_pool_min_size > self.postgres_pool_max_size:
            raise ValueError("postgres_pool_min_size must not exceed postgres_pool_max_size")
        if self.drain_timeout_seconds > self.lease_seconds:
            raise ValueError("drain_timeout_seconds must not exceed lease_seconds")
        return self


def validate_runtime_configuration(settings: Settings) -> None:
    credentials = settings.tenant_credentials
    if not credentials:
        raise RuntimeError("Audit Projector requires at least one tenant credential")
    if settings.deployment_environment != "production":
        return
    if not settings.identity_inventory_json:
        raise RuntimeError("production projector identity inventory is missing")
    identities = parse_projector_identity_inventory(settings.identity_inventory_json)
    raw_credentials = json.loads(settings.tenant_credentials_json.get_secret_value())
    validate_projector_credential_bindings(identities, raw_credentials)
    if urlsplit(settings.keycloak_base_url).scheme != "https":
        raise RuntimeError("production Keycloak transport must use HTTPS")
    if urlsplit(settings.audit_service_base_url).scheme != "https":
        raise RuntimeError("production Audit Service transport must use HTTPS")
    parsed_dsn = urlsplit(settings.postgres_dsn)
    sslmode = parse_qs(parsed_dsn.query).get("sslmode", [])
    if not sslmode or sslmode[-1] not in {"require", "verify-ca", "verify-full"}:
        raise RuntimeError("production PostgreSQL transport must require TLS")
