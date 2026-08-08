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

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("EMG_KEYCLOAK_BASE_URL", "http://keycloak:8080")
REALM = os.environ.get("EMG_KEYCLOAK_REALM", "emg")
ADMIN_USER = os.environ.get("KEYCLOAK_ADMIN", "admin")
ADMIN_PASSWORD = os.environ["KEYCLOAK_ADMIN_PASSWORD"]

ACTING_SERVICE_CLIENT_ID = "emg-studio-bff"
AUDIENCE_CLIENT_IDS = ["emg-knowledge-graph-audience"]
ALLOW_POLICY_NAME = "allow-emg-studio-bff-exchange"


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
    status, body = _http("GET", f"/admin/realms/{REALM}/clients?clientId={client_id}", token)
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


def main() -> None:
    print(f"waiting for {BASE_URL}/realms/{REALM} ...")
    wait_healthy()

    token = admin_token()

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

    print("done — emg-studio-bff may now exchange to:", ", ".join(AUDIENCE_CLIENT_IDS))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surfaced as a non-zero exit, not swallowed
        print(f"provisioning failed: {exc}", file=sys.stderr)
        sys.exit(1)
