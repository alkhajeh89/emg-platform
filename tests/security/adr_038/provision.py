"""Post-import provisioning for the ADR-038 non-production verification realm.

Everything here is a step that CANNOT be expressed declaratively in the
realm-import JSON (`realm/emg-verification-realm.json`) and was determined
experimentally against a real, running Keycloak 25.0 container — not
assumed. See docs/security/adr-038/02_KEYCLOAK_VERIFICATION_CONFIG.md for
the full experimental trail (including two dead ends this script
deliberately avoids: renaming a fine-grained permission collides with
Keycloak's convention-based lookup by name, and claim projection during
token exchange is governed by the *audience* client's default scopes, not
the requesting client's).

Run with the Keycloak container already up (docker-compose.verification.yml)
and KC_ADMIN_PASSWORD available via .env.verification.local. Idempotent:
safe to re-run after `down -v && up -d` or mid-session.

Produces (never committed — see .gitignore):
  - regenerated client secrets for every confidential client
  - fresh passwords for both human test users
  - fine-grained admin permissions granting ONLY emg-verification-bff
    token-exchange rights to audience-a and audience-b (both the source
    client `emg-verification-ropc` and each target audience client need
    their own token-exchange permission enabled and policy-attached --
    Keycloak's exchange check requires both legs)
  - emg-verification-bff-unauthorized is deliberately left with no grant
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("EMG_VERIFICATION_KC_BASE_URL", "http://localhost:8180")
REALM = "emg-verification"
HERE = Path(__file__).parent
ENV_FILE = HERE / ".env.verification.local"

CONFIDENTIAL_CLIENTS = {
    "emg-verification-ropc": "EMG_VERIFICATION_ROPC_SECRET",
    "emg-verification-bff": "EMG_VERIFICATION_BFF_SECRET",
    "emg-verification-bff-unauthorized": "EMG_VERIFICATION_BFF_UNAUTHORIZED_SECRET",
    "emg-svc-knowledge-graph-writer": "EMG_VERIFICATION_KG_WRITER_SECRET",
}
HUMAN_USERS = {
    "human-principal-a": "EMG_VERIFICATION_HUMAN_A_PASSWORD",
    "human-principal-b": "EMG_VERIFICATION_HUMAN_B_PASSWORD",
}
AUTHORIZED_ACTING_SERVICE = "emg-verification-bff"
AUDIENCE_CLIENTS = ["emg-verification-audience-a", "emg-verification-audience-b"]
EXCHANGE_SOURCE_CLIENT = "emg-verification-ropc"
ALLOW_POLICY_NAME = "allow-emg-verification-bff-exchange"


def _http(
    method: str, path: str, token: str | None = None, body: dict | None = None
) -> tuple[int, object]:
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
    import urllib.parse

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
    admin_password = os.environ["EMG_VERIFICATION_KC_ADMIN_PASSWORD"]
    resp = _form(
        "/realms/master/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "verification-admin",
            "password": admin_password,
        },
    )
    return resp["access_token"]


def get_client_uuid(token: str, client_id: str) -> str:
    status, body = _http("GET", f"/admin/realms/{REALM}/clients?clientId={client_id}", token)
    if status != 200 or not body:
        raise RuntimeError(f"client lookup failed for {client_id}: {status} {body}")
    return body[0]["id"]


def get_user_id(token: str, username: str) -> str:
    status, body = _http(
        "GET", f"/admin/realms/{REALM}/users?username={username}&exact=true", token
    )
    if status != 200 or not body:
        raise RuntimeError(f"user lookup failed for {username}: {status} {body}")
    return body[0]["id"]


def regenerate_client_secret(token: str, client_uuid: str) -> str:
    status, body = _http(
        "POST", f"/admin/realms/{REALM}/clients/{client_uuid}/client-secret", token
    )
    if status != 200:
        raise RuntimeError(f"secret regeneration failed: {status} {body}")
    return body["value"]


def set_user_password(token: str, user_id: str, password: str) -> None:
    status, body = _http(
        "PUT",
        f"/admin/realms/{REALM}/users/{user_id}/reset-password",
        token,
        {"type": "password", "value": password, "temporary": False},
    )
    if status != 204:
        raise RuntimeError(f"password set failed: {status} {body}")


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
    """Create the 'allow <bff> to exchange' client policy if absent; return its id.

    Idempotent by name: GET first, since re-POSTing an existing policy name
    raises a DB unique-constraint error (discovered experimentally — the
    same failure mode as re-PUTting a permission's own name, see the
    resource-server policy table's (name, resource_server_id) unique index).
    """
    status, existing = _http(
        "GET",
        f"/admin/realms/{REALM}/clients/{realm_mgmt_uuid}/authz/resource-server/policy?name={ALLOW_POLICY_NAME}",
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
    """Attach policy_id to an already-enabled 'token-exchange' scope permission.

    CRITICAL: the PUT to attach a policy must preserve the permission's
    existing auto-generated name
    (`token-exchange.permission.client.<uuid>`). Overwriting it with a
    literal "token-exchange" collides with every other client's identically
    literal-named permission (Keycloak enforces (name, resource_server_id)
    uniqueness) and, worse, silently breaks Keycloak's OWN internal
    convention-based lookup for that permission -- it stops being found and
    the exchange fails closed with "client not allowed to exchange to
    audience" even though a policy is still attached. This was the actual
    root cause the first time through; fixed here structurally by always
    reading the current name before writing.
    """
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
    if not ENV_FILE.exists():
        print(f"missing {ENV_FILE} -- run ./generate_env.sh first", file=sys.stderr)
        sys.exit(1)
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)

    print(f"waiting for {BASE_URL}/realms/{REALM} ...")
    wait_healthy()

    token = admin_token()
    generated: dict[str, str] = {}

    print("regenerating client secrets ...")
    client_uuids: dict[str, str] = {}
    for client_id, env_name in CONFIDENTIAL_CLIENTS.items():
        uuid = get_client_uuid(token, client_id)
        client_uuids[client_id] = uuid
        generated[env_name] = regenerate_client_secret(token, uuid)
    generated["EMG_VERIFICATION_BFF_CLIENT_UUID"] = client_uuids["emg-verification-bff"]
    generated["EMG_VERIFICATION_BFF_UNAUTHORIZED_CLIENT_UUID"] = client_uuids[
        "emg-verification-bff-unauthorized"
    ]

    print("setting human test-user passwords ...")
    for username, env_name in HUMAN_USERS.items():
        uid = get_user_id(token, username)
        pwd = secrets.token_hex(24)
        set_user_password(token, uid, pwd)
        generated[env_name] = pwd

    print("granting token-exchange permission to the AUTHORIZED acting service only ...")
    realm_mgmt_uuid = get_client_uuid(token, "realm-management")
    bff_uuid = client_uuids[AUTHORIZED_ACTING_SERVICE]

    # Enabling fine-grained permissions on at least one client is what
    # provisions realm-management's authorization resource server in the
    # first place -- the client-policy endpoint 404s if nothing has enabled
    # permissions yet. Enable on all three legs (source + both audiences)
    # before creating/attaching the policy.
    source_uuid = get_client_uuid(token, EXCHANGE_SOURCE_CLIENT)
    audience_uuids = [get_client_uuid(token, a) for a in AUDIENCE_CLIENTS]
    perm_ids = {}
    for uuid in [source_uuid, *audience_uuids]:
        enable_resp = enable_fine_grained_permissions(token, uuid)
        perm_ids[uuid] = enable_resp["scopePermissions"]["token-exchange"]

    policy_id = ensure_client_policy(token, realm_mgmt_uuid, bff_uuid)

    for uuid in [source_uuid, *audience_uuids]:
        attach_policy_to_permission(token, realm_mgmt_uuid, perm_ids[uuid], policy_id)

    print(
        "NOT granting anything to emg-verification-bff-unauthorized "
        "(negative-test fixture, left denied)."
    )

    # Preserve admin password already in the env file; overwrite generated values.
    lines = [
        line
        for line in ENV_FILE.read_text().splitlines()
        if line.split("=", 1)[0] not in generated and line.strip()
    ]
    lines += [f"{k}={v}" for k, v in generated.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    print(f"wrote {len(generated)} generated values to {ENV_FILE} (gitignored)")


if __name__ == "__main__":
    main()
