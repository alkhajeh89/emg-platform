from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "infra/environments/production"
sys.path.insert(0, str(ROOT / "tools/ci"))
from validate_production_provisioning import ProvisioningValidationError  # noqa: E402
from validate_production_provisioning import validate as validate_provisioning  # noqa: E402


def _objects() -> list[dict]:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(OVERLAY)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [document for document in yaml.safe_load_all(rendered) if document]


def test_production_manifests_render_without_literal_secrets() -> None:
    objects = _objects()
    assert objects
    assert not [obj for obj in objects if obj["kind"] == "Secret"]
    assert len([obj for obj in objects if obj["kind"] == "ExternalSecret"]) == 7


def test_deployments_are_single_replica_hardened_and_digest_pinned() -> None:
    deployments = [obj for obj in _objects() if obj["kind"] == "Deployment"]
    assert {obj["metadata"]["name"] for obj in deployments} == {
        "emg-identity",
        "emg-audit",
        "emg-audit-projector",
        "emg-knowledge-graph",
        "emg-studio",
        "emg-studio-bff",
    }
    digest = re.compile(r"^[^:]+(?:/[^:]+)+@sha256:[0-9a-f]{64}$")
    for deployment in deployments:
        assert deployment["spec"]["replicas"] == 1
        assert deployment["spec"]["strategy"]["type"] == "Recreate"
        pod = deployment["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for container in pod["containers"]:
            assert digest.match(container["image"])
            assert ":latest" not in container["image"]
            assert container["resources"]["requests"]
            assert container["resources"]["limits"]
            security = container["securityContext"]
            assert security["allowPrivilegeEscalation"] is False
            assert security["readOnlyRootFilesystem"] is True
            assert security["capabilities"]["drop"] == ["ALL"]
            if deployment["metadata"]["name"] == "emg-audit-projector":
                assert container["livenessProbe"]["exec"]
                assert container["readinessProbe"]["exec"]
            else:
                assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
                assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"


def test_one_shot_jobs_are_hardened_and_digest_pinned() -> None:
    jobs = [obj for obj in _objects() if obj["kind"] == "Job"]
    assert {job["metadata"]["name"] for job in jobs} == {
        "emg-database-bootstrap",
        "emg-audit-migration",
        "emg-knowledge-graph-migration",
        "emg-keycloak-provision",
        "emg-provisioning-validate",
    }
    digest = re.compile(r"^[^:]+(?:/[^:]+)+@sha256:[0-9a-f]{64}$")
    for job in jobs:
        pod = job["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        for container in pod["containers"]:
            assert digest.match(container["image"])
            assert container["resources"]["requests"]
            assert container["resources"]["limits"]
            security = container["securityContext"]
            assert security["allowPrivilegeEscalation"] is False
            assert security["readOnlyRootFilesystem"] is True
            assert security["capabilities"]["drop"] == ["ALL"]


def test_privileged_credentials_are_confined_to_jobs() -> None:
    objects = _objects()
    deployment_text = yaml.safe_dump_all([obj for obj in objects if obj["kind"] == "Deployment"])
    assert "migration-postgres-dsn" not in deployment_text
    assert "admin-postgres-dsn" not in deployment_text
    assert "admin-password" not in deployment_text
    assert "admin-username" not in deployment_text

    jobs = {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "Job"}
    bootstrap = yaml.safe_dump(jobs["emg-database-bootstrap"])
    assert "admin-postgres-dsn" in bootstrap
    assert "database-bootstrap" in bootstrap
    assert "migration-postgres-dsn" in yaml.safe_dump(jobs["emg-audit-migration"])
    assert "migration-postgres-dsn" in yaml.safe_dump(jobs["emg-knowledge-graph-migration"])
    provision = yaml.safe_dump(jobs["emg-keycloak-provision"])
    assert "admin-password" in provision
    assert "admin-username" in provision
    assert "EMG_KNOWLEDGE_GRAPH_API_STORE_BACKEND" in yaml.safe_dump(
        jobs["emg-knowledge-graph-migration"]
    )


def test_adr_041_provisioning_contract_is_complete_and_ordered() -> None:
    objects = _objects()
    validate_provisioning(objects)
    stages = {
        obj["metadata"]["name"]: obj["metadata"]
        .get("annotations", {})
        .get("emg.platform/bootstrap-stage")
        for obj in objects
        if obj["kind"] in {"Job", "Deployment"}
    }
    assert stages["emg-database-bootstrap"] == "10-database-roles"
    assert stages["emg-audit-migration"] == "20-postgresql-migrations"
    assert stages["emg-keycloak-provision"] == "30-keycloak-projector-clients"
    assert stages["emg-provisioning-validate"] == "50-consistency-validation"
    assert stages["emg-audit"] == "60-audit-service"
    assert stages["emg-audit-projector"] == "70-audit-projector"


def test_provisioning_validation_rejects_inventory_or_allow_list_divergence() -> None:
    objects = _objects()
    audit = next(
        obj
        for obj in objects
        if obj["kind"] == "Deployment" and obj["metadata"]["name"] == "emg-audit"
    )
    audit["spec"]["template"]["spec"]["containers"][0]["env"].append(
        {"name": "EMG_AUDIT_PROJECTOR_CLIENT_IDS", "value": "unknown-client"}
    )

    with pytest.raises(ProvisioningValidationError, match="independent projector allow-list"):
        validate_provisioning(objects)


def test_external_secrets_are_provider_neutral() -> None:
    external_secrets = [obj for obj in _objects() if obj["kind"] == "ExternalSecret"]
    rendered = yaml.safe_dump_all(external_secrets).lower()
    assert "clustersecretstore" in rendered
    assert "emg-production-secrets" in rendered
    for vendor in ("aws", "azure", "gcp", "vault", "oracle", "alibaba"):
        assert vendor not in rendered


def test_network_policy_defaults_to_deny_and_allows_dns_explicitly() -> None:
    policies = {
        obj["metadata"]["name"]: obj for obj in _objects() if obj["kind"] == "NetworkPolicy"
    }
    default_deny = policies["emg-default-deny"]["spec"]
    assert default_deny["policyTypes"] == ["Ingress", "Egress"]
    assert "ingress" not in default_deny and "egress" not in default_deny
    dns_ports = policies["emg-dns-egress"]["spec"]["egress"][0]["ports"]
    assert {(port["protocol"], port["port"]) for port in dns_ports} == {
        ("UDP", 53),
        ("TCP", 53),
    }


def test_environment_specific_external_egress_is_not_silently_enabled() -> None:
    production_kustomization = (OVERLAY / "kustomization.yaml").read_text(encoding="utf-8")
    assert "external-egress.example.yaml" not in production_kustomization


def test_studio_is_the_only_public_ingress_and_proxies_only_to_the_bff() -> None:
    objects = _objects()
    ingress = next(obj for obj in objects if obj["kind"] == "Ingress")
    backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
    assert backend == {"name": "emg-studio", "port": {"name": "http"}}

    policies = {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "NetworkPolicy"}
    studio_ingress = policies["emg-studio-ingress"]["spec"]["ingress"][0]
    assert studio_ingress["ports"] == [{"protocol": "TCP", "port": 3000}]
    bff_ingress = policies["emg-studio-bff-ingress"]["spec"]["ingress"][0]
    assert bff_ingress["from"] == [
        {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "emg-studio"}}}
    ]
    studio_egress = policies["emg-studio-to-bff-egress"]["spec"]["egress"][0]
    assert studio_egress["to"] == [
        {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "emg-studio-bff"}}}
    ]


def test_identity_spool_uses_persistent_storage() -> None:
    objects = _objects()
    identity = next(
        obj
        for obj in objects
        if obj["kind"] == "Deployment" and obj["metadata"]["name"] == "emg-identity"
    )
    volumes = identity["spec"]["template"]["spec"]["volumes"]
    assert any(
        volume.get("persistentVolumeClaim", {}).get("claimName") == "emg-identity-audit-spool"
        for volume in volumes
    )
    config = next(
        obj
        for obj in objects
        if obj["kind"] == "ConfigMap" and obj["metadata"]["name"] == "emg-identity-config"
    )
    assert config["data"]["EMG_IDENTITY_AUDIT_SPOOL_PATH"].startswith(
        "/var/lib/emg-identity/audit-spool/"
    )
