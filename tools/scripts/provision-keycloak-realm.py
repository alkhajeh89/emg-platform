#!/usr/bin/env python3
"""Final correction-sprint Finding 6 — canonical-runtime Keycloak
post-import provisioning.

Keycloak 25's fine-grained token-exchange permission has no declarative
realm-import syntax (confirmed experimentally during the ADR-038 capability
verification, `docs/security/adr-038/02_KEYCLOAK_VERIFICATION_CONFIG.md`).
Without this script, a genuinely fresh `docker compose up` imports the
canonical realm correctly but leaves the Studio BFF unable to complete a
real token exchange against Knowledge Graph's audience (`403 access_denied`
on every attempt) until someone runs this by hand.

This is the canonical-runtime counterpart of
`tests/security/adr_038/provision.py`, which proved this exact sequence
(including the two documented dead ends it avoids — never overwrite an
auto-generated permission's name; enable fine-grained permissions on all
three legs, source and both target audiences, before creating/attaching a
policy) against a real, isolated Keycloak instance. This script grants
exactly one production-shaped permission: `emg-studio-bff` may exchange to
`emg-knowledge-graph-audience`. It is idempotent — safe to run on every
`docker compose up`.

Stdlib only (no `httpx`/`requests`) so this runs in a bare `python:slim`
container with no package install step.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from emg_common_types import (
    ProjectorIdentity,
    parse_projector_identity_inventory,
    validate_projector_credential_bindings,
)

BASE_URL = os.environ.get("EMG_KEYCLOAK_BASE_URL", "http://keycloak:8080")
REALM = os.environ.get("EMG_KEYCLOAK_REALM", "emg")
ADMIN_USER = os.environ.get("KEYCLOAK_ADMIN", "admin")
ADMIN_PASSWORD = os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "")

ACTING_SERVICE_CLIENT_ID = "emg-studio-bff"
AUDIENCE_CLIENT_IDS = ["emg-knowledge-graph-audience"]
ALLOW_POLICY_NAME = "allow-emg-studio-bff-exchange"
PROJECTOR_ROLES = ("service-account", "svc-audit-projector")
PROJECTOR_DEFAULT_SCOPES = (
    "emg-internal-services-audience",
    "emg-service-security-claims",
)
PROJECTOR_TENANT_MAPPER = "emg-projector-tenant-id"


def _http(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw.decode(errors="replace")


def _form(path: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def wait_healthy(timeout_s: int = 90) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, _ = _http("GET", f"/realms/{REALM}")
            if status == 200:
                return
        except Exception:  # noqa: BLE001 - best-effort readiness poll
            pass
        time.sleep(2)
    raise RuntimeError(f"Keycloak/{REALM} not reachable after {timeout_s}s")


def admin_token() -> str:
    if not ADMIN_PASSWORD:
        raise RuntimeError("KEYCLOAK_ADMIN_PASSWORD is required")
    resp = _form(
        "/realms/master/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
        },
    )
    return resp["access_token"]


def get_client_uuid(token: str, client_id: str) -> str:
    query = urllib.parse.urlencode({"clientId": client_id})
    status, body = _http("GET", f"/admin/realms/{REALM}/clients?{query}", token)
    if status != 200 or not body:
        raise RuntimeError(f"client lookup failed for {client_id}: {status} {body}")
    return body[0]["id"]


def enable_fine_grained_permissions(token: str, client_uuid: str) -> dict:
    status, body = _http(
        "PUT",
        f"/admin/realms/{REALM}/clients/{client_uuid}/management/permissions",
        token,
        {"enabled": True},
    )
    if status != 200:
        raise RuntimeError(f"enabling permissions failed: {status} {body}")
    return body


def ensure_client_policy(token: str, realm_mgmt_uuid: str, allowed_client_uuid: str) -> str:
    """Idempotent by name: GET first (see module docstring — re-POSTing an
    existing policy name raises a DB unique-constraint error)."""
    status, existing = _http(
        "GET",
        f"/admin/realms/{REALM}/clients/{realm_mgmt_uuid}/authz/resource-server/policy"
        f"?name={ALLOW_POLICY_NAME}",
        token,
    )
    if status == 200 and existing:
        return existing[0]["id"]
    status, body = _http(
        "POST",
        f"/admin/realms/{REALM}/clients/{realm_mgmt_uuid}/authz/resource-server/policy/client",
        token,
        {"name": ALLOW_POLICY_NAME, "clients": [allowed_client_uuid]},
    )
    if status != 201:
        raise RuntimeError(f"policy creation failed: {status} {body}")
    return body["id"]


def attach_policy_to_permission(
    token: str, realm_mgmt_uuid: str, perm_id: str, policy_id: str
) -> None:
    """CRITICAL: preserve the permission's existing auto-generated name.
    Overwriting it with a literal string collides with every other client's
    identically-literal-named permission and silently breaks Keycloak's own
    internal convention-based lookup for it (documented dead end, see
    module docstring)."""
    status, current = _http(
        "GET",
        f"/admin/realms/{REALM}/clients/{realm_mgmt_uuid}/authz/resource-server/permission/{perm_id}",
        token,
    )
    if status != 200:
        raise RuntimeError(f"permission lookup failed: {status} {current}")
    preserved_name = current["name"]

    status, body = _http(
        "PUT",
        f"/admin/realms/{REALM}/clients/{realm_mgmt_uuid}/authz/resource-server/permission/scope/{perm_id}",
        token,
        {"id": perm_id, "name": preserved_name, "policies": [policy_id]},
    )
    if status not in (200, 201):
        raise RuntimeError(f"permission update failed: {status} {body}")


def _projector_configuration() -> tuple[tuple[ProjectorIdentity, ...], dict[str, str]]:
    inventory_json = os.environ.get("EMG_PROJECTOR_IDENTITY_INVENTORY_JSON", "")
    credentials_json = os.environ.get("EMG_AUDIT_PROJECTOR_TENANT_CREDENTIALS_JSON", "")
    if not inventory_json and not credentials_json:
        return (), {}
    if not inventory_json or not credentials_json:
        raise RuntimeError("projector inventory and tenant credentials must both be configured")
    identities = parse_projector_identity_inventory(inventory_json)
    try:
        raw_credentials = json.loads(credentials_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("projector tenant credentials must be valid JSON") from exc
    validate_projector_credential_bindings(identities, raw_credentials)
    secrets = {item["client_id"]: item["client_secret"] for item in raw_credentials}
    return identities, secrets


def _realm_role(token: str, role_name: str, *, create: bool) -> dict:
    encoded = urllib.parse.quote(role_name, safe="")
    status, role = _http("GET", f"/admin/realms/{REALM}/roles/{encoded}", token)
    if status == 200:
        return role
    if status != 404 or not create:
        raise RuntimeError(f"required realm role {role_name} is absent")
    status, body = _http(
        "POST",
        f"/admin/realms/{REALM}/roles",
        token,
        {"name": role_name, "description": "ADR-041 Audit Projector service role"},
    )
    if status not in (201, 204):
        raise RuntimeError(f"creating realm role {role_name} failed: {status} {body}")
    status, role = _http("GET", f"/admin/realms/{REALM}/roles/{encoded}", token)
    if status != 200:
        raise RuntimeError(f"created realm role {role_name} cannot be read")
    return role


def _client(token: str, client_id: str) -> dict | None:
    query = urllib.parse.urlencode({"clientId": client_id})
    status, body = _http("GET", f"/admin/realms/{REALM}/clients?{query}", token)
    if status != 200:
        raise RuntimeError(f"client lookup failed for {client_id}: {status}")
    if not body:
        return None
    if len(body) != 1:
        raise RuntimeError(f"client lookup for {client_id} is ambiguous")
    status, full = _http("GET", f"/admin/realms/{REALM}/clients/{body[0]['id']}", token)
    if status != 200:
        raise RuntimeError(f"client read failed for {client_id}: {status}")
    return full


def _projector_client_representation(identity: ProjectorIdentity, secret: str) -> dict:
    return {
        "clientId": identity.client_id,
        "name": f"EMG Audit Projector — {identity.tenant_id}",
        "description": "ADR-041 tenant-scoped Audit Projector service identity",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "bearerOnly": False,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": True,
        "clientAuthenticatorType": "client-secret",
        "secret": secret,
        "redirectUris": [],
        "webOrigins": [],
        "fullScopeAllowed": False,
        "attributes": {"access.token.lifespan": "300"},
    }


def _reject_conflicting_client_mode(client: dict, identity: ProjectorIdentity) -> None:
    required_false = (
        "publicClient",
        "bearerOnly",
        "standardFlowEnabled",
        "implicitFlowEnabled",
        "directAccessGrantsEnabled",
    )
    if any(client.get(field, False) for field in required_false):
        raise RuntimeError(f"existing projector client {identity.client_id} has conflicting mode")
    if not client.get("serviceAccountsEnabled", False):
        raise RuntimeError(
            f"existing projector client {identity.client_id} is not service-account enabled"
        )
    if client.get("clientAuthenticatorType") not in (None, "client-secret"):
        raise RuntimeError(
            f"existing projector client {identity.client_id} has conflicting authenticator"
        )


def _client_scopes(token: str) -> dict[str, dict]:
    status, scopes = _http("GET", f"/admin/realms/{REALM}/client-scopes", token)
    if status != 200:
        raise RuntimeError("Keycloak client-scope lookup failed")
    by_name = {item["name"]: item for item in scopes}
    missing = set(PROJECTOR_DEFAULT_SCOPES) - set(by_name)
    if missing:
        raise RuntimeError(f"required client scopes are absent: {sorted(missing)}")
    return by_name


def _ensure_default_scopes(token: str, client_uuid: str) -> None:
    scopes = _client_scopes(token)
    status, assigned = _http(
        "GET", f"/admin/realms/{REALM}/clients/{client_uuid}/default-client-scopes", token
    )
    if status != 200:
        raise RuntimeError("projector default-client-scope lookup failed")
    assigned_ids = {item["id"] for item in assigned}
    for scope_name in PROJECTOR_DEFAULT_SCOPES:
        scope = scopes[scope_name]
        if scope["id"] in assigned_ids:
            continue
        status, _ = _http(
            "PUT",
            f"/admin/realms/{REALM}/clients/{client_uuid}/default-client-scopes/{scope['id']}",
            token,
        )
        if status != 204:
            raise RuntimeError(f"assigning projector client scope {scope_name} failed")


def _ensure_tenant_mapper(token: str, client_uuid: str, identity: ProjectorIdentity) -> None:
    status, mappers = _http(
        "GET", f"/admin/realms/{REALM}/clients/{client_uuid}/protocol-mappers/models", token
    )
    if status != 200:
        raise RuntimeError("projector protocol-mapper lookup failed")
    existing = next((item for item in mappers if item.get("name") == PROJECTOR_TENANT_MAPPER), None)
    expected_config = {
        "claim.name": "tenant_id",
        "claim.value": identity.tenant_id,
        "jsonType.label": "String",
        "access.token.claim": "true",
        "id.token.claim": "false",
        "userinfo.token.claim": "false",
    }
    if existing is not None:
        config = existing.get("config", {})
        if (
            config.get("claim.name") != "tenant_id"
            or config.get("claim.value") != identity.tenant_id
        ):
            raise RuntimeError(
                f"existing projector client {identity.client_id} has conflicting tenant binding"
            )
        return
    status, body = _http(
        "POST",
        f"/admin/realms/{REALM}/clients/{client_uuid}/protocol-mappers/models",
        token,
        {
            "name": PROJECTOR_TENANT_MAPPER,
            "protocol": "openid-connect",
            "protocolMapper": "oidc-hardcoded-claim-mapper",
            "config": expected_config,
        },
    )
    if status != 201:
        raise RuntimeError(f"creating projector tenant mapper failed: {status} {body}")


def _ensure_service_account_roles(token: str, client_uuid: str) -> None:
    roles = [_realm_role(token, name, create=True) for name in PROJECTOR_ROLES]
    status, user = _http(
        "GET", f"/admin/realms/{REALM}/clients/{client_uuid}/service-account-user", token
    )
    if status != 200:
        raise RuntimeError("projector service-account lookup failed")
    status, current = _http(
        "GET", f"/admin/realms/{REALM}/users/{user['id']}/role-mappings/realm", token
    )
    if status != 200:
        raise RuntimeError("projector service-account role lookup failed")
    current_names = {role["name"] for role in current}
    missing = [role for role in roles if role["name"] not in current_names]
    if missing:
        status, _ = _http(
            "POST",
            f"/admin/realms/{REALM}/users/{user['id']}/role-mappings/realm",
            token,
            missing,
        )
        if status != 204:
            raise RuntimeError("assigning projector service-account roles failed")

    # With fullScopeAllowed=false, Keycloak emits only the intersection of the
    # service-account user's roles and the client's role scope mappings.
    status, scoped = _http(
        "GET", f"/admin/realms/{REALM}/clients/{client_uuid}/scope-mappings/realm", token
    )
    if status != 200:
        raise RuntimeError("projector client role-scope lookup failed")
    scoped_names = {role["name"] for role in scoped}
    missing_scope = [role for role in roles if role["name"] not in scoped_names]
    if missing_scope:
        status, _ = _http(
            "POST",
            f"/admin/realms/{REALM}/clients/{client_uuid}/scope-mappings/realm",
            token,
            missing_scope,
        )
        if status != 204:
            raise RuntimeError("assigning projector client role scope failed")


def ensure_projector_client(token: str, identity: ProjectorIdentity, secret: str) -> None:
    existing = _client(token, identity.client_id)
    desired = _projector_client_representation(identity, secret)
    if existing is None:
        status, _ = _http("POST", f"/admin/realms/{REALM}/clients", token, desired)
        if status != 201:
            raise RuntimeError(f"creating projector client {identity.client_id} failed: {status}")
        existing = _client(token, identity.client_id)
        if existing is None:
            raise RuntimeError(f"created projector client {identity.client_id} cannot be read")
    else:
        _reject_conflicting_client_mode(existing, identity)
        updated = dict(existing)
        updated.update(desired)
        status, _ = _http("PUT", f"/admin/realms/{REALM}/clients/{existing['id']}", token, updated)
        if status != 204:
            raise RuntimeError(f"updating projector client {identity.client_id} failed: {status}")
        existing = _client(token, identity.client_id)
        if existing is None:
            raise RuntimeError(f"updated projector client {identity.client_id} cannot be read")

    client_uuid = existing["id"]
    _ensure_default_scopes(token, client_uuid)
    _ensure_tenant_mapper(token, client_uuid, identity)
    _ensure_service_account_roles(token, client_uuid)


def _decode_token_payload(access_token: str) -> dict:
    try:
        encoded = access_token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        return json.loads(base64.urlsafe_b64decode(encoded.encode()))
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Keycloak returned a malformed projector access token") from exc


def verify_projector_client(token: str, identity: ProjectorIdentity, secret: str) -> None:
    client = _client(token, identity.client_id)
    if client is None:
        raise RuntimeError(f"projector client {identity.client_id} is absent")
    _reject_conflicting_client_mode(client, identity)
    client_uuid = client["id"]

    scopes = _client_scopes(token)
    status, assigned = _http(
        "GET", f"/admin/realms/{REALM}/clients/{client_uuid}/default-client-scopes", token
    )
    assigned_ids = {item["id"] for item in assigned or []}
    if status != 200 or any(
        scopes[scope_name]["id"] not in assigned_ids for scope_name in PROJECTOR_DEFAULT_SCOPES
    ):
        raise RuntimeError(f"projector client {identity.client_id} default scopes are inconsistent")

    status, mappers = _http(
        "GET", f"/admin/realms/{REALM}/clients/{client_uuid}/protocol-mappers/models", token
    )
    mapper = next(
        (item for item in mappers or [] if item.get("name") == PROJECTOR_TENANT_MAPPER),
        None,
    )
    if (
        status != 200
        or mapper is None
        or mapper.get("config", {}).get("claim.value") != identity.tenant_id
    ):
        raise RuntimeError(f"projector client {identity.client_id} tenant claim is inconsistent")

    status, user = _http(
        "GET", f"/admin/realms/{REALM}/clients/{client_uuid}/service-account-user", token
    )
    if status != 200:
        raise RuntimeError(f"projector client {identity.client_id} service account is absent")
    status, roles = _http(
        "GET", f"/admin/realms/{REALM}/users/{user['id']}/role-mappings/realm", token
    )
    if status != 200 or not set(PROJECTOR_ROLES).issubset({role["name"] for role in roles}):
        raise RuntimeError(f"projector client {identity.client_id} required roles are absent")

    token_response = _form(
        f"/realms/{REALM}/protocol/openid-connect/token",
        {
            "grant_type": "client_credentials",
            "client_id": identity.client_id,
            "client_secret": secret,
        },
    )
    payload = _decode_token_payload(token_response["access_token"])
    audience = payload.get("aud", ())
    audiences = {audience} if isinstance(audience, str) else set(audience)
    token_roles = set(payload.get("realm_access", {}).get("roles", ()))
    if payload.get("tenant_id") != identity.tenant_id:
        raise RuntimeError(f"projector client {identity.client_id} token tenant is inconsistent")
    if "emg-internal-services" not in audiences:
        raise RuntimeError(f"projector client {identity.client_id} token audience is inconsistent")
    missing_roles = set(PROJECTOR_ROLES) - token_roles
    if missing_roles:
        raise RuntimeError(
            f"projector client {identity.client_id} token is missing required roles: "
            f"{sorted(missing_roles)}"
        )


def provision_projector_clients(
    token: str, identities: tuple[ProjectorIdentity, ...], secrets: dict[str, str]
) -> None:
    for role in PROJECTOR_ROLES:
        _realm_role(token, role, create=True)
    for identity in identities:
        ensure_projector_client(token, identity, secrets[identity.client_id])
        verify_projector_client(token, identity, secrets[identity.client_id])


def validate_projector_clients(
    token: str, identities: tuple[ProjectorIdentity, ...], secrets: dict[str, str]
) -> None:
    for role in PROJECTOR_ROLES:
        _realm_role(token, role, create=False)
    for identity in identities:
        verify_projector_client(token, identity, secrets[identity.client_id])


def main() -> None:
    parser = argparse.ArgumentParser(description="EMG canonical Keycloak provisioner")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    print(f"waiting for {BASE_URL}/realms/{REALM} ...")
    wait_healthy()

    token = admin_token()

    identities, secrets = _projector_configuration()
    if args.validate_only:
        if not identities:
            raise RuntimeError("projector identity inventory is required for validation")
        validate_projector_clients(token, identities, secrets)
        print(f"validated {len(identities)} tenant-scoped projector client(s)")
        return

    print(
        f"granting token-exchange permission: {ACTING_SERVICE_CLIENT_ID} -> {AUDIENCE_CLIENT_IDS}"
    )
    realm_mgmt_uuid = get_client_uuid(token, "realm-management")
    source_uuid = get_client_uuid(token, ACTING_SERVICE_CLIENT_ID)
    audience_uuids = [get_client_uuid(token, a) for a in AUDIENCE_CLIENT_IDS]

    perm_ids: dict[str, str] = {}
    for uuid in [source_uuid, *audience_uuids]:
        enable_resp = enable_fine_grained_permissions(token, uuid)
        perm_ids[uuid] = enable_resp["scopePermissions"]["token-exchange"]

    policy_id = ensure_client_policy(token, realm_mgmt_uuid, source_uuid)

    for uuid in [source_uuid, *audience_uuids]:
        attach_policy_to_permission(token, realm_mgmt_uuid, perm_ids[uuid], policy_id)

    if identities:
        provision_projector_clients(token, identities, secrets)

    print(
        "done — token exchange configured and tenant-scoped projector clients provisioned:",
        len(identities),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surfaced as a non-zero exit, not swallowed
        print(f"provisioning failed: {exc}", file=sys.stderr)
        sys.exit(1)
