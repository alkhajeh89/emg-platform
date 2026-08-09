from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from emg_common_types import parse_projector_identity_inventory

ROOT = Path(__file__).resolve().parents[2]
PROVISIONER = ROOT / "tools/scripts/provision-keycloak-realm.py"


@pytest.fixture
def provisioner():
    spec = importlib.util.spec_from_file_location("rc1h_keycloak_provisioner", PROVISIONER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identities():
    return parse_projector_identity_inventory(
        json.dumps(
            {
                "version": 1,
                "projector_identities": [
                    {"tenant_id": "tenant-b", "client_id": "projector-b"},
                    {"tenant_id": "tenant-a", "client_id": "projector-a"},
                ],
            }
        )
    )


def test_keycloak_projector_contract_is_non_interactive_and_tenant_scoped(provisioner) -> None:
    identity = _identities()[0]
    representation = provisioner._projector_client_representation(identity, "external-secret")

    assert representation["clientId"] == "projector-a"
    assert representation["publicClient"] is False
    assert representation["bearerOnly"] is False
    assert representation["standardFlowEnabled"] is False
    assert representation["implicitFlowEnabled"] is False
    assert representation["directAccessGrantsEnabled"] is False
    assert representation["serviceAccountsEnabled"] is True
    assert provisioner.PROJECTOR_ROLES == ("service-account", "svc-audit-projector")
    assert "external-secret" not in json.dumps(
        {"tenant_id": identity.tenant_id, "client_id": identity.client_id}
    )


def test_two_tenant_clients_provision_and_verify_idempotently(provisioner, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        provisioner,
        "_realm_role",
        lambda token, role, create: {"id": role, "name": role},
    )
    monkeypatch.setattr(
        provisioner,
        "ensure_projector_client",
        lambda token, identity, secret: calls.append(("ensure", identity.client_id)),
    )
    monkeypatch.setattr(
        provisioner,
        "verify_projector_client",
        lambda token, identity, secret: calls.append(("verify", identity.client_id)),
    )
    identities = _identities()
    secrets = {"projector-a": "secret-a", "projector-b": "secret-b"}

    provisioner.provision_projector_clients("admin-token", identities, secrets)
    provisioner.provision_projector_clients("admin-token", identities, secrets)

    assert (
        calls
        == [
            ("ensure", "projector-a"),
            ("verify", "projector-a"),
            ("ensure", "projector-b"),
            ("verify", "projector-b"),
        ]
        * 2
    )


def test_existing_cross_tenant_or_interactive_client_fails_closed(provisioner) -> None:
    identity = _identities()[0]
    with pytest.raises(RuntimeError, match="conflicting mode"):
        provisioner._reject_conflicting_client_mode(
            {"standardFlowEnabled": True, "serviceAccountsEnabled": True}, identity
        )
