"""Authenticated, tenant-checked delivery through the existing Audit API."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import httpx
import jwt
from emg_audit_client import SubmittedAuditEvent

from .config import Settings, TenantCredential
from .errors import (
    CredentialMismatchError,
    PermanentDeliveryError,
    RetryableDeliveryError,
    ShutdownRequested,
)


class AuditDeliveryClient:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=settings.http_timeout_seconds)
        self._owns_client = client is None

    def _token(self, credential: TenantCredential) -> str:
        try:
            response = self._client.post(
                self._settings.token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": credential.client_id,
                    "client_secret": credential.client_secret.get_secret_value(),
                },
            )
        except httpx.HTTPError as exc:
            raise RetryableDeliveryError("projector token request failed") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise RetryableDeliveryError("projector token service is unavailable")
        if response.status_code != 200:
            raise PermanentDeliveryError("projector credential was rejected")
        try:
            token = response.json()["access_token"]
            if not isinstance(token, str) or not token:
                raise TypeError
            claims: dict[str, Any] = jwt.decode(
                token,
                options={"verify_signature": False, "verify_aud": False},
                algorithms=["RS256"],
            )
        except (KeyError, TypeError, ValueError, jwt.PyJWTError) as exc:
            raise PermanentDeliveryError("projector token response is invalid") from exc
        token_tenant = claims.get("tenant_id")
        token_client = claims.get("azp") or claims.get("client_id")
        if token_tenant != credential.tenant_id or token_client != credential.client_id:
            raise CredentialMismatchError(
                "issued projector token does not match configured tenant/client binding"
            )
        return token

    def deliver(
        self,
        events: Iterable[SubmittedAuditEvent],
        *,
        credential: TenantCredential,
        shutdown_requested: Callable[[], bool],
    ) -> None:
        token = self._token(credential)
        for event in events:
            if shutdown_requested():
                raise ShutdownRequested("projector shutdown interrupted delivery")
            try:
                response = self._client.post(
                    f"{self._settings.audit_service_base_url}/audit/events",
                    json=event.model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise RetryableDeliveryError("Audit Service delivery failed") from exc
            if response.status_code >= 500 or response.status_code == 429:
                raise RetryableDeliveryError("Audit Service is unavailable")
            if response.status_code != 200:
                raise PermanentDeliveryError("Audit Service rejected projected event")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
