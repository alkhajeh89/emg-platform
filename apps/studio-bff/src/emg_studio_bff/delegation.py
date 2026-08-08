"""OAuth 2.0 Token Exchange (RFC 8693) — ADR-038 Chapter VI/VII.

**No caching (Phase 2B Required Change #4).** Every call to
`exchange_for_delegated_credential` performs a fresh token-exchange request
against Keycloak. There is no cache dict, no reuse-by-key lookup, nothing
that could return a previously-issued credential. ADR-038 §7.9 permits
caching; this batch deliberately does not implement it, to minimize the
security surface of the first production delegation path. Credential
caching may be added later as a separate, reviewed optimization.

The one Keycloak-claim-reading adapter for the exchanged (Delegated
Credential) token lives here — this mirrors, and is informed directly by,
`tests/security/adr_038/claim_adapter.py`'s experimentally-determined
finding: Acting Service identity is carried by `azp`, not `act`, in
Keycloak 25's token-exchange response. Nothing downstream of this module
(the KG proxy router, any future audience) reads a raw claim name.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import Settings


@dataclass(frozen=True, slots=True)
class DelegatedCredential:
    """ADR-038 Chapter VII's technology-neutral Delegated Credential shape."""

    access_token: str
    acting_service: str | None
    audience: str
    expires_in: int


class DelegationError(Exception):
    """Raised for any token-exchange failure. Callers MUST fail closed —
    there is no fallback identity, cached credential, or service-only
    substitute (ADR-038 §9.10 Invariant — Fail Closed)."""


async def exchange_for_delegated_credential(
    settings: Settings, *, subject_token: str, audience: str
) -> DelegatedCredential:
    """Perform ONE RFC 8693 token-exchange call, authenticating as this
    BFF's own confidential client (ADR-038 §7.2: only the Authorization
    Authority-recognized Acting Service may request an exchange).
    `subject_token` is the human's own current, verified Keycloak access
    token — never a previously-exchanged Delegated Credential (ADR-038
    §7.8's "reuse SHALL NOT extend lifetime" is honored here by construction:
    there is nothing to reuse, since nothing is cached)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.token_endpoint,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret.get_secret_value(),
                "subject_token": subject_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "audience": audience,
            },
        )
    if response.status_code != 200:
        raise DelegationError(
            f"token exchange for audience {audience!r} failed: {response.status_code}"
        )
    body = response.json()
    access_token = body["access_token"]
    return DelegatedCredential(
        access_token=access_token,
        acting_service=_peek_acting_service(access_token),
        audience=audience,
        expires_in=int(body["expires_in"]),
    )


def _peek_acting_service(delegated_access_token: str) -> str | None:
    """Read `azp` from the (already Keycloak-issued, transport-trusted —
    this token came directly from the token endpoint's own TLS response
    body, not from an untrusted party) exchanged token, purely for local
    logging/observability. This value is NEVER used for any trust decision
    in the BFF itself — only the downstream Platform Service's own
    independent validation (ADR-038 §7.6/AC-9) is authoritative."""
    import jwt

    try:
        payload = jwt.decode(delegated_access_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return None
    azp = payload.get("azp")
    return azp if isinstance(azp, str) else None
