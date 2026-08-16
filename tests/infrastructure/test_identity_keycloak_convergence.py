from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROVISIONER = ROOT / "tools/scripts/provision-keycloak-realm.py"


@pytest.fixture
def provisioner():
    spec = importlib.util.spec_from_file_location("identity_keycloak_provisioner", PROVISIONER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract(provisioner, client_id: str = "emg-identity-service"):
    return next(
        contract
        for contract in provisioner.IDENTITY_CLIENT_CONTRACTS
        if contract.client_id == client_id
    )


def _client(provisioner, contract, **overrides):
    value = provisioner._identity_client_representation(contract, "not-returned-by-client-read")
    value.pop("secret")
    value["id"] = f"uuid-{contract.client_id}"
    value.update(overrides)
    return value


def _isolate_reconciliation(provisioner, monkeypatch) -> None:
    monkeypatch.setattr(provisioner, "_ensure_identity_scopes", lambda *args: False)
    monkeypatch.setattr(provisioner, "_ensure_identity_roles", lambda *args: False)
    monkeypatch.setattr(provisioner, "_reject_identity_protocol_mapper_drift", lambda *args: None)
    monkeypatch.setattr(
        provisioner,
        "validate_identity_client",
        lambda token, contract, secret: provisioner.IdentityClientEvidence(
            contract.client_id, "existing", "verified", "verified"
        ),
    )


def test_absent_identity_client_is_created_without_secret_in_evidence(
    provisioner, monkeypatch
) -> None:
    contract = _contract(provisioner)
    expected = _client(provisioner, contract)
    reads = iter((None, expected))
    requests: list[tuple[str, str, dict | None]] = []
    monkeypatch.setattr(provisioner, "_client", lambda *args: next(reads))
    monkeypatch.setattr(
        provisioner,
        "_http",
        lambda method, path, token=None, body=None: (
            requests.append((method, path, body)) or (201, None)
        ),
    )
    _isolate_reconciliation(provisioner, monkeypatch)

    evidence = provisioner.ensure_identity_client("admin", contract, "fixture-secret")

    assert evidence.existence == "created"
    assert evidence.secret_material == "converged"
    assert requests[0][0] == "POST"
    assert requests[0][2]["secret"] == "fixture-secret"
    assert "fixture-secret" not in json.dumps(evidence._asdict())


def test_correct_identity_client_is_a_repeatable_no_op(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner)
    monkeypatch.setattr(provisioner, "_client", lambda *args: _client(provisioner, contract))
    monkeypatch.setattr(provisioner, "_client_secret_matches", lambda *args: True)
    requests: list[str] = []
    monkeypatch.setattr(
        provisioner,
        "_http",
        lambda method, *args, **kwargs: (requests.append(method) or (204, None)),
    )
    _isolate_reconciliation(provisioner, monkeypatch)

    first = provisioner.ensure_identity_client("admin", contract, "fixture-secret")
    second = provisioner.ensure_identity_client("admin", contract, "fixture-secret")

    assert first == second
    assert first.configuration == "verified"
    assert requests == []


def test_non_sensitive_metadata_drift_is_converged(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner)
    monkeypatch.setattr(
        provisioner,
        "_client",
        lambda *args: _client(provisioner, contract, name="stale display name"),
    )
    monkeypatch.setattr(provisioner, "_client_secret_matches", lambda *args: True)
    requests: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(
        provisioner,
        "_http",
        lambda method, path, token=None, body=None: (
            requests.append((method, body)) or (204, None)
        ),
    )
    _isolate_reconciliation(provisioner, monkeypatch)

    evidence = provisioner.ensure_identity_client("admin", contract, "fixture-secret")

    assert evidence.configuration == "converged"
    assert requests == [("PUT", requests[0][1])]
    assert requests[0][1]["name"] == contract.name
    assert "secret" not in requests[0][1]


def test_security_sensitive_drift_fails_closed_without_write(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner)
    monkeypatch.setattr(
        provisioner,
        "_client",
        lambda *args: _client(provisioner, contract, publicClient=True),
    )
    writes: list[str] = []
    monkeypatch.setattr(
        provisioner,
        "_http",
        lambda method, *args, **kwargs: (writes.append(method) or (204, None)),
    )

    with pytest.raises(RuntimeError, match="security-sensitive drift"):
        provisioner.ensure_identity_client("admin", contract, "fixture-secret")
    assert writes == []


def test_secret_mismatch_is_converged_without_disclosure(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner)
    monkeypatch.setattr(provisioner, "_client", lambda *args: _client(provisioner, contract))
    monkeypatch.setattr(provisioner, "_client_secret_matches", lambda *args: False)
    requests: list[dict] = []
    monkeypatch.setattr(
        provisioner,
        "_http",
        lambda method, path, token=None, body=None: (requests.append(body) or (204, None)),
    )
    _isolate_reconciliation(provisioner, monkeypatch)

    evidence = provisioner.ensure_identity_client("admin", contract, "fixture-secret")

    assert evidence.secret_material == "converged"
    assert requests[0]["secret"] == "fixture-secret"
    assert "fixture-secret" not in repr(evidence)


def test_missing_secret_material_fails_before_provider_access(provisioner, monkeypatch) -> None:
    monkeypatch.delenv("EMG_IDENTITY_KEYCLOAK_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("EMG_IDENTITY_SERVICE_CLIENT_SECRET", "fixture-service-secret")

    with pytest.raises(RuntimeError, match="secret material is missing") as exc:
        provisioner._identity_client_secrets()
    assert "fixture-service-secret" not in str(exc.value)


def test_provider_error_and_ambiguous_client_state_fail_closed(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner)
    client_lookup = provisioner._client
    monkeypatch.setattr(provisioner, "_client", lambda *args: None)
    monkeypatch.setattr(provisioner, "_http", lambda *args, **kwargs: (503, None))
    with pytest.raises(RuntimeError, match="creating Identity client.*503"):
        provisioner.ensure_identity_client("admin", contract, "fixture-secret")

    monkeypatch.setattr(
        provisioner,
        "_http",
        lambda *args, **kwargs: (200, [{"id": "one"}, {"id": "two"}]),
    )
    with pytest.raises(RuntimeError, match="ambiguous"):
        client_lookup("admin", contract.client_id)


def test_malformed_secret_response_and_unexpected_scope_fail_closed(
    provisioner, monkeypatch
) -> None:
    contract = _contract(provisioner)
    monkeypatch.setattr(provisioner, "_http", lambda *args, **kwargs: (200, {}))
    with pytest.raises(RuntimeError, match="cannot be inspected"):
        provisioner._client_secret_matches("admin", "uuid", "fixture-secret")

    responses = iter(
        (
            (
                200,
                [
                    {"id": f"required-{index}", "name": scope}
                    for index, scope in enumerate(contract.default_scopes)
                ],
            ),
            (200, [{"id": "unexpected", "name": "emg-unexpected-scope"}]),
            (200, []),
        )
    )
    monkeypatch.setattr(provisioner, "_http", lambda *args, **kwargs: next(responses))
    with pytest.raises(RuntimeError, match="unexpected governed scopes"):
        provisioner._identity_scope_state("admin", "uuid", contract)


def test_unexpected_optional_scope_fails_closed(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner)
    responses = iter(
        (
            (
                200,
                [
                    {"id": f"required-{index}", "name": scope}
                    for index, scope in enumerate(contract.default_scopes)
                ],
            ),
            (
                200,
                [
                    {"id": f"required-{index}", "name": scope}
                    for index, scope in enumerate(contract.default_scopes)
                ],
            ),
            (200, [{"id": "custom", "name": "custom-privileged-claims"}]),
        )
    )
    monkeypatch.setattr(provisioner, "_http", lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="unexpected optional scopes"):
        provisioner._identity_scope_state("admin", "uuid", contract)


def test_unexpected_privileged_realm_role_fails_closed(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner, "emg-svc-identity")
    responses = iter(
        (
            (200, {"id": "service-account-user"}),
            (200, [{"id": "admin", "name": "realm-admin"}]),
        )
    )
    monkeypatch.setattr(provisioner, "_http", lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="unexpected governed roles"):
        provisioner._identity_role_state("admin", "uuid", contract)


def test_unexpected_client_role_fails_closed(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner, "emg-svc-identity")
    responses = iter(
        (
            (200, {"id": "service-account-user"}),
            (
                200,
                [
                    {"id": "service-account", "name": "service-account"},
                    {"id": "svc-identity", "name": "svc-identity"},
                ],
            ),
            (
                200,
                {
                    "clientMappings": {
                        "realm-management": {
                            "mappings": [{"id": "manage-users", "name": "manage-users"}]
                        }
                    }
                },
            ),
        )
    )
    monkeypatch.setattr(provisioner, "_http", lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="unexpected client roles"):
        provisioner._identity_role_state("admin", "uuid", contract)


def test_unexpected_direct_protocol_mapper_fails_closed(provisioner, monkeypatch) -> None:
    contract = _contract(provisioner)
    monkeypatch.setattr(
        provisioner,
        "_http",
        lambda *args, **kwargs: (
            200,
            [{"name": "privileged-claim", "protocolMapper": "oidc-hardcoded-claim-mapper"}],
        ),
    )

    with pytest.raises(RuntimeError, match="unexpected direct protocol mappers"):
        provisioner._reject_identity_protocol_mapper_drift("admin", "uuid", contract)


def test_identity_contracts_are_canonical_and_distinct(provisioner) -> None:
    contracts = {contract.client_id: contract for contract in provisioner.IDENTITY_CLIENT_CONTRACTS}
    assert set(contracts) == {"emg-identity-service", "emg-svc-identity"}
    assert contracts["emg-identity-service"].direct_access_grants is True
    assert contracts["emg-svc-identity"].direct_access_grants is False
    assert contracts["emg-svc-identity"].realm_roles == (
        "service-account",
        "svc-identity",
    )


def test_release_evidence_is_deterministic_and_redacted(provisioner) -> None:
    evidence = (
        provisioner.IdentityClientEvidence(
            "emg-identity-service", "existing", "verified", "verified"
        ),
        provisioner.IdentityClientEvidence("emg-svc-identity", "existing", "verified", "verified"),
    )

    first = provisioner._structured_evidence(evidence, projector_count=2, validate_only=True)
    second = provisioner._structured_evidence(evidence, projector_count=2, validate_only=True)

    assert first == second
    assert first == (
        '{"identity_clients":[{"client_id":"emg-identity-service",'
        '"configuration":"verified","existence":"existing",'
        '"secret_material":"verified","validation":"passed"},'
        '{"client_id":"emg-svc-identity","configuration":"verified",'
        '"existence":"existing","secret_material":"verified",'
        '"validation":"passed"}],"projector_clients_validated":2,'
        '"result":"passed"}'
    )
    assert "fixture-secret" not in first
