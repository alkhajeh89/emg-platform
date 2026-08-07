"""Thin, dependency-free HTTP wrapper around the isolated verification
Keycloak's token endpoint. Deliberately returns raw dict responses (never
raises on an OAuth error body) so negative tests can assert on the exact
error/status Keycloak produced, rather than on an exception shape this
module invents.

This is the ONLY module in the test suite allowed to know the token
endpoint's request shape (form-encoded OAuth grants). Response CLAIM shape
is a separate concern, owned by claim_adapter.py.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenResponse:
    status: int
    body: dict


def _post_form(base_url: str, path: str, fields: dict) -> TokenResponse:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{base_url}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            import json

            return TokenResponse(resp.status, json.loads(resp.read()))
    except urllib.error.HTTPError as exc:
        import json

        raw = exc.read()
        try:
            return TokenResponse(exc.code, json.loads(raw))
        except json.JSONDecodeError:
            return TokenResponse(
                exc.code, {"error": "non_json_response", "raw": raw.decode(errors="replace")}
            )


def ropc_login(
    base_url: str, realm: str, client_id: str, client_secret: str, username: str, password: str
) -> TokenResponse:
    """Human Principal login. ADR-035 D-2 explicitly reserves ROPC for
    service/test purposes -- this harness is exactly that, never a browser
    path."""
    return _post_form(
        base_url,
        f"/realms/{realm}/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": password,
            "scope": "openid",
        },
    )


def client_credentials(
    base_url: str, realm: str, client_id: str, client_secret: str
) -> TokenResponse:
    """Acting Service's own authentication (ADR-038 Ch. VII confidential-client requirement)."""
    return _post_form(
        base_url,
        f"/realms/{realm}/protocol/openid-connect/token",
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )


def token_exchange(
    base_url: str,
    realm: str,
    client_id: str,
    client_secret: str,
    subject_token: str,
    audience: str,
    *,
    subject_token_type: str = "urn:ietf:params:oauth:token-type:access_token",
) -> TokenResponse:
    """RFC 8693 token exchange -- the Delegated Credential issuance call."""
    return _post_form(
        base_url,
        f"/realms/{realm}/protocol/openid-connect/token",
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": client_id,
            "client_secret": client_secret,
            "subject_token": subject_token,
            "subject_token_type": subject_token_type,
            "audience": audience,
        },
    )


def refresh(
    base_url: str, realm: str, client_id: str, client_secret: str, refresh_token: str
) -> TokenResponse:
    return _post_form(
        base_url,
        f"/realms/{realm}/protocol/openid-connect/token",
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    )
