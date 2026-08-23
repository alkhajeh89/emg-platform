from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "infra/environments/production"
STAGING_OVERLAY = ROOT / "infra/environments/staging"
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


def _staging_objects() -> list[dict]:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(STAGING_OVERLAY)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [document for document in yaml.safe_load_all(rendered) if document]


def test_production_manifests_render_without_literal_secrets() -> None:
    objects = _objects()
    assert objects
    assert not [obj for obj in objects if obj["kind"] == "Secret"]
    assert len([obj for obj in objects if obj["kind"] == "ExternalSecret"]) == 10


def test_staging_manifests_render_without_literal_secrets() -> None:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(STAGING_OVERLAY)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    objects = [document for document in yaml.safe_load_all(rendered) if document]
    assert objects
    assert not [obj for obj in objects if obj["kind"] == "Secret"]


def test_deployments_are_single_replica_hardened_and_digest_pinned() -> None:
    deployments = [obj for obj in _objects() if obj["kind"] == "Deployment"]
    assert {obj["metadata"]["name"] for obj in deployments} == {
        "emg-identity",
        "emg-audit",
        "emg-audit-projector",
        "emg-knowledge-graph",
        "emg-studio",
        "emg-studio-bff",
        "emg-identity-recovery-qualify",
        "emg-recovery-authority",
        "emg-recovery-signer",
    }
    digest = re.compile(r"^[^:]+(?:/[^:]+)+@sha256:[0-9a-f]{64}$")
    for deployment in deployments:
        # ADR-043 Amendment 1 A9.4 Phase 2: the recovery-qualification
        # workload defaults to zero replicas -- it exists only to be scaled
        # to one, on demand, by the recovery coordinator during a fenced
        # recovery window (see infra/kubernetes/base/identity-recovery.yaml).
        if deployment["metadata"]["name"] == "emg-identity-recovery-qualify":
            assert deployment["spec"]["replicas"] == 0
        else:
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
        "emg-identity-migration",
        "emg-identity-recovery-reconcile",
        "emg-knowledge-graph-migration",
        "emg-keycloak-provision",
        "emg-provisioning-validate",
        "emg-provisioning-validate-recovery",
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


def test_recovery_schedule_is_bounded_hardened_and_externally_configured() -> None:
    objects = _objects()
    cronjobs = [obj for obj in objects if obj["kind"] == "CronJob"]
    assert len(cronjobs) == 1
    cron = cronjobs[0]
    assert cron["metadata"]["name"] == "emg-postgresql-backup"
    spec = cron["spec"]
    assert spec["schedule"] == "0 1 * * *"
    assert spec["timeZone"] == "Etc/UTC"
    assert spec["concurrencyPolicy"] == "Forbid"
    assert spec["startingDeadlineSeconds"] == 3600
    job = spec["jobTemplate"]["spec"]
    assert job["activeDeadlineSeconds"] == 7200
    assert job["backoffLimit"] == 1
    pod = job["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["serviceAccountName"] == "emg-postgresql-backup"
    assert pod["securityContext"]["runAsNonRoot"] is True
    container = pod["containers"][0]
    assert container["resources"]["requests"] and container["resources"]["limits"]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    env = {entry["name"]: entry for entry in container["env"]}
    assert "value" not in env["EMG_BACKUP_DSN"]
    assert env["EMG_BACKUP_DSN"]["valueFrom"]["secretKeyRef"]
    assert env["EMG_BACKUP_KEY_REFERENCE"]["valueFrom"]["secretKeyRef"]
    assert env["EMG_RETENTION_MINIMUM_DAYS"]["value"] == "35"
    assert env["EMG_RETENTION_MINIMUM_COUNT"]["value"] == "2"
    repository = next(volume for volume in pod["volumes"] if volume["name"] == "repository")
    assert repository["persistentVolumeClaim"]["claimName"] == ("emg-postgresql-backup-repository")
    assert not [
        obj
        for obj in objects
        if obj["kind"] == "PersistentVolumeClaim"
        and obj["metadata"]["name"] == "emg-postgresql-backup-repository"
    ]


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
    assert "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN" in bootstrap
    assert "EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN" in bootstrap
    assert "EMG_IDENTITY_MIGRATION_POSTGRES_DSN" in bootstrap
    assert "EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN" in bootstrap
    assert "emg-knowledge-graph-secrets" in bootstrap
    assert "migration-postgres-dsn" in yaml.safe_dump(jobs["emg-audit-migration"])
    assert "migration-postgres-dsn" in yaml.safe_dump(jobs["emg-knowledge-graph-migration"])
    identity_migration = yaml.safe_dump(jobs["emg-identity-migration"])
    assert "migration-postgres-dsn" in identity_migration
    assert "refresh-postgres-dsn" not in identity_migration
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
    assert stages["emg-identity-migration"] == "20-postgresql-migrations"
    assert stages["emg-keycloak-provision"] == "30-keycloak-clients"
    assert stages["emg-provisioning-validate"] == "50-consistency-validation"
    assert stages["emg-identity"] == "60-identity-service"
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


@pytest.mark.parametrize(
    "missing_name",
    (
        "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN",
        "EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN",
        "EMG_IDENTITY_MIGRATION_POSTGRES_DSN",
        "EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN",
    ),
)
def test_provisioning_validation_rejects_missing_kg_bootstrap_dsn(missing_name: str) -> None:
    objects = _objects()
    bootstrap = next(
        obj
        for obj in objects
        if obj["kind"] == "Job" and obj["metadata"]["name"] == "emg-database-bootstrap"
    )
    container = bootstrap["spec"]["template"]["spec"]["containers"][0]
    container["env"] = [entry for entry in container["env"] if entry["name"] != missing_name]

    with pytest.raises(ProvisioningValidationError, match="credentials are incomplete"):
        validate_provisioning(objects)


def test_provisioning_validation_rejects_wrong_kg_bootstrap_secret_key() -> None:
    objects = _objects()
    bootstrap = next(
        obj
        for obj in objects
        if obj["kind"] == "Job" and obj["metadata"]["name"] == "emg-database-bootstrap"
    )
    env = {
        entry["name"]: entry
        for entry in bootstrap["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    env["EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN"]["valueFrom"]["secretKeyRef"][
        "key"
    ] = "migration-postgres-dsn"

    with pytest.raises(ProvisioningValidationError, match="credential wiring is invalid"):
        validate_provisioning(objects)


@pytest.mark.parametrize(
    "job_name,container_index",
    (("emg-keycloak-provision", 0), ("emg-provisioning-validate", 1)),
)
def test_provisioning_validation_rejects_wrong_identity_keycloak_secret_wiring(
    job_name: str, container_index: int
) -> None:
    objects = _objects()
    job = next(
        obj for obj in objects if obj["kind"] == "Job" and obj["metadata"]["name"] == job_name
    )
    env = {
        entry["name"]: entry
        for entry in job["spec"]["template"]["spec"]["containers"][container_index]["env"]
    }
    env["EMG_IDENTITY_KEYCLOAK_CLIENT_SECRET"]["valueFrom"]["secretKeyRef"][
        "key"
    ] = "service-client-secret"

    with pytest.raises(ProvisioningValidationError, match="credential wiring is invalid"):
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


# --- S6 TLS fix (P0-1/P1-1): recovery-authority <-> recovery-signer -------


def _recovery_signer_configmap(objects: list[dict]) -> dict:
    return next(
        obj
        for obj in objects
        if obj["kind"] == "ConfigMap" and obj["metadata"]["name"] == "emg-recovery-signer-config"
    )


def _recovery_authority_configmap(objects: list[dict]) -> dict:
    return next(
        obj
        for obj in objects
        if obj["kind"] == "ConfigMap" and obj["metadata"]["name"] == "emg-recovery-authority-config"
    )


def test_staging_overlay_resolves_staging_signer_dns() -> None:
    """Adversarial-matrix item O."""
    objects = _staging_objects()
    signer_config = _recovery_signer_configmap(objects)
    authority_config = _recovery_authority_configmap(objects)
    assert (
        signer_config["data"]["RECOVERY_SIGNER_SERVICE_AUDIENCE"]
        == "https://emg-recovery-signer.emg-staging.svc.cluster.local:8443"
    )
    assert (
        authority_config["data"]["RECOVERY_AUTHORITY_SIGNER_ENDPOINT"]
        == "https://emg-recovery-signer.emg-staging.svc.cluster.local:8443"
    )
    assert (
        authority_config["data"]["RECOVERY_AUTHORITY_SIGNER_AUDIENCE"]
        == "https://emg-recovery-signer.emg-staging.svc.cluster.local:8443"
    )
    assert "example-namespace" not in signer_config["data"]["RECOVERY_SIGNER_SERVICE_AUDIENCE"]
    assert "emg-production" not in signer_config["data"]["RECOVERY_SIGNER_SERVICE_AUDIENCE"]


def test_production_overlay_resolves_production_signer_dns() -> None:
    """Adversarial-matrix item P."""
    objects = _objects()
    signer_config = _recovery_signer_configmap(objects)
    authority_config = _recovery_authority_configmap(objects)
    assert (
        signer_config["data"]["RECOVERY_SIGNER_SERVICE_AUDIENCE"]
        == "https://emg-recovery-signer.emg-production.svc.cluster.local:8443"
    )
    assert (
        authority_config["data"]["RECOVERY_AUTHORITY_SIGNER_ENDPOINT"]
        == "https://emg-recovery-signer.emg-production.svc.cluster.local:8443"
    )
    assert "example-namespace" not in signer_config["data"]["RECOVERY_SIGNER_SERVICE_AUDIENCE"]
    assert "emg-staging" not in signer_config["data"]["RECOVERY_SIGNER_SERVICE_AUDIENCE"]


def test_staging_and_production_signer_dns_differ() -> None:
    staging_config = _recovery_signer_configmap(_staging_objects())
    production_config = _recovery_signer_configmap(_objects())
    assert (
        staging_config["data"]["RECOVERY_SIGNER_SERVICE_AUDIENCE"]
        != production_config["data"]["RECOVERY_SIGNER_SERVICE_AUDIENCE"]
    )


def test_recovery_signer_allow_insecure_is_false_in_every_overlay() -> None:
    """Adversarial-matrix item G: allowInsecure must never be enabled in a
    committed environment overlay."""
    for objects in (_objects(), _staging_objects()):
        signer_config = _recovery_signer_configmap(objects)
        assert signer_config["data"]["RECOVERY_SIGNER_ALLOW_INSECURE"] == "false"


def test_recovery_signer_serves_https_and_mounts_tls_secret_by_reference_only() -> None:
    objects = _objects()
    deployment = next(
        obj
        for obj in objects
        if obj["kind"] == "Deployment" and obj["metadata"]["name"] == "emg-recovery-signer"
    )
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    ports = {port["name"]: port for port in container["ports"]}
    assert "https" in ports and ports["https"]["containerPort"] == 8443
    assert "http" not in ports

    for probe_name in ("startupProbe", "livenessProbe", "readinessProbe"):
        assert container[probe_name]["httpGet"]["scheme"] == "HTTPS"

    volumes = {v["name"]: v for v in deployment["spec"]["template"]["spec"]["volumes"]}
    assert volumes["tls"]["secret"]["secretName"] == "emg-recovery-signer-tls"
    # Never a literal certificate/key value anywhere in the rendered
    # manifest -- only a name reference to a Secret this repository does
    # not create (see test_production_manifests_render_without_literal_secrets).
    rendered = yaml.safe_dump(deployment)
    for marker in ("BEGIN CERTIFICATE", "PRIVATE KEY"):
        assert marker not in rendered

    service = next(
        obj
        for obj in objects
        if obj["kind"] == "Service" and obj["metadata"]["name"] == "emg-recovery-signer"
    )
    assert service["spec"].get("type", "ClusterIP") == "ClusterIP"
    assert service["spec"]["ports"] == [{"name": "https", "port": 8443, "targetPort": "https"}]


def test_recovery_signer_tls_secret_is_sourced_from_external_secrets_only() -> None:
    external_secrets = {
        obj["metadata"]["name"]: obj for obj in _objects() if obj["kind"] == "ExternalSecret"
    }
    tls_secret = external_secrets["emg-recovery-signer-tls"]
    keys = {entry["secretKey"] for entry in tls_secret["spec"]["data"]}
    assert keys == {"tls.crt", "tls.key"}
    assert tls_secret["spec"]["target"]["name"] == "emg-recovery-signer-tls"


def test_recovery_signer_has_no_public_ingress() -> None:
    """Adversarial-matrix item Q: no Ingress resource names the signer,
    anywhere, in either overlay."""
    for objects in (_objects(), _staging_objects()):
        ingresses = [obj for obj in objects if obj["kind"] == "Ingress"]
        for ingress in ingresses:
            rendered = yaml.safe_dump(ingress)
            assert "emg-recovery-signer" not in rendered


def test_recovery_signer_network_policy_still_restricted_to_authority_only() -> None:
    """Adversarial-matrix item R, re-confirmed after the TLS fix: the
    signer's ingress NetworkPolicy is unchanged -- only the authority
    runtime may reach it, on the same port the container/Service now
    honestly advertise as HTTPS."""
    policies = {
        obj["metadata"]["name"]: obj for obj in _objects() if obj["kind"] == "NetworkPolicy"
    }
    signer_ingress = policies["emg-recovery-signer-ingress"]["spec"]["ingress"][0]
    assert signer_ingress["from"] == [
        {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "emg-recovery-authority"}}}
    ]
    assert signer_ingress["ports"] == [{"protocol": "TCP", "port": 8443}]

    authority_egress = policies["emg-recovery-authority-to-signer-egress"]["spec"]["egress"][0]
    assert authority_egress["to"] == [
        {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "emg-recovery-signer"}}}
    ]


# --- Wave 2 Track E fsGroup fix: mounted Secret volumes must actually be
# readable by the non-root runtime user, not merely present -------------
#
# Real GKE qualification (Wave 2 Track E) proved that Kubernetes mounts a
# Secret volume as root:root regardless of defaultMode's permission bits:
# with runAsUser/runAsGroup: 10001 and no fsGroup, cmd/recovery-signer's
# fail-closed TLS startup check failed on every real cluster with
# "permission denied" -- this had never been caught because no prior wave
# had ever deployed these manifests to a real cluster (kubectl kustomize
# rendering, which the rest of this file exercises, cannot detect a
# runtime file-permission failure). These tests encode the fix so the
# defect cannot silently return.


def _recovery_signer_deployment(objects: list[dict]) -> dict:
    return next(
        obj
        for obj in objects
        if obj["kind"] == "Deployment" and obj["metadata"]["name"] == "emg-recovery-signer"
    )


def _recovery_authority_deployment(objects: list[dict]) -> dict:
    return next(
        obj
        for obj in objects
        if obj["kind"] == "Deployment" and obj["metadata"]["name"] == "emg-recovery-authority"
    )


@pytest.mark.parametrize("objects_fn", [_objects, _staging_objects])
def test_recovery_signer_fsgroup_matches_runtime_group(objects_fn) -> None:
    pod = _recovery_signer_deployment(objects_fn())["spec"]["template"]["spec"]
    security = pod["securityContext"]
    assert security["runAsNonRoot"] is True
    assert security["runAsUser"] == 10001
    assert security["runAsGroup"] == 10001
    # The load-bearing assertion: without fsGroup, the mounted `tls` Secret
    # volume below is unreadable by this non-root runtime user on any real
    # cluster (empirically confirmed against the real emg-staging GKE
    # cluster during Track E) -- runAsGroup alone does not change a mounted
    # Secret's on-disk group ownership.
    assert security["fsGroup"] == 10001
    assert security["fsGroup"] != 0
    assert security["runAsUser"] != 0
    assert security["runAsGroup"] != 0


@pytest.mark.parametrize("objects_fn", [_objects, _staging_objects])
def test_recovery_signer_tls_secret_mode_excludes_world_access(objects_fn) -> None:
    """No new item 3/4: the TLS Secret volume's defaultMode must keep the
    'other' permission bits at zero (no world-readable private key) --
    fsGroup, not a looser defaultMode, is the correct fix for group-read
    access (see Track E's provider fact-check: fsGroup is honored for
    Secret volumes on this GKE/Kubernetes version)."""
    volumes = {
        v["name"]: v
        for v in _recovery_signer_deployment(objects_fn())["spec"]["template"]["spec"]["volumes"]
    }
    mode = volumes["tls"]["secret"]["defaultMode"]
    assert mode & 0o007 == 0, "TLS private key Secret must not be world-accessible"
    assert mode <= 0o440


def test_recovery_signer_has_no_chown_workaround() -> None:
    """The fsGroup fix must not be replaced or supplemented by a
    privileged init-container chown hack, root execution, or a permissive
    defaultMode -- fsGroup is the only mechanism used."""
    deployment = _recovery_signer_deployment(_objects())
    pod = deployment["spec"]["template"]["spec"]
    assert "initContainers" not in pod
    for container in pod["containers"]:
        command = " ".join(container.get("command", []) + container.get("args", []))
        assert "chown" not in command
        assert "chmod" not in command
        security = container["securityContext"]
        assert security["allowPrivilegeEscalation"] is False
        assert security["capabilities"]["drop"] == ["ALL"]
        assert security["readOnlyRootFilesystem"] is True


def test_recovery_authority_does_not_mount_signer_tls_secret() -> None:
    """Adversarial-matrix item: the authority runtime must never be able
    to read the signer's private TLS key through its own pod spec."""
    deployment = _recovery_authority_deployment(_objects())
    rendered = yaml.safe_dump(deployment)
    assert "emg-recovery-signer-tls" not in rendered


def test_recovery_authority_secret_volumes_have_compatible_fsgroup() -> None:
    """General invariant, scoped to recovery-authority only: if any
    current or future overlay gives this deployment a Secret-typed
    volume (e.g. a private CA bundle for signer TLS verification), its
    pod must declare an fsGroup compatible with its own runAsGroup, or
    that mount is unreadable on a real cluster exactly as recovery-signer's
    was before the Track E fix. Currently the base manifest mounts no
    Secret here, so this is a forward-looking regression guard, not a
    claim that such a mount exists today."""
    pod = _recovery_authority_deployment(_objects())["spec"]["template"]["spec"]
    secret_volumes = [v for v in pod["volumes"] if "secret" in v]
    if not secret_volumes:
        return
    security = pod["securityContext"]
    assert security.get("fsGroup") is not None
    assert security["fsGroup"] == security["runAsGroup"]


def test_recovery_signer_and_authority_fsgroup_consistent_across_overlays() -> None:
    """Item 9: staging and production must render this fix identically --
    the fsGroup fix is a base-manifest property, not something either
    overlay patches independently."""
    for deployment_fn in (_recovery_signer_deployment, _recovery_authority_deployment):
        staging_security = deployment_fn(_staging_objects())["spec"]["template"]["spec"][
            "securityContext"
        ]
        production_security = deployment_fn(_objects())["spec"]["template"]["spec"][
            "securityContext"
        ]
        assert staging_security == production_security


# --- Wave 2 Track E DNS NetworkPolicy fix: kube-dns Service ClusterIP -----
#
# Real GKE Dataplane V2 qualification (Wave 2 Track E) proved that a
# combined namespaceSelector+podSelector destination restriction
# (kube-system + k8s-app: kube-dns) permits DNS traffic addressed
# directly to the kube-dns backend pod's own IP but NOT to the kube-dns
# Service's ClusterIP -- the address every pod's /etc/resolv.conf
# actually uses. An ipBlock rule for that ClusterIP (any breadth, up to
# 0.0.0.0/0) was also empirically proven not to work: ipBlock does not
# match in-cluster-addressed traffic on this cluster. namespaceSelector
# alone (dropping podSelector) was the only expression that empirically
# restored real DNS resolution via the ClusterIP. These tests encode
# that fix and its bounds so it cannot silently regress or expand.


def _dns_egress_policy(objects: list[dict]) -> dict:
    return next(
        obj
        for obj in objects
        if obj["kind"] == "NetworkPolicy"
        if obj["metadata"]["name"] == "emg-dns-egress"
    )


def test_dns_egress_uses_namespace_selector_for_kube_system() -> None:
    rule = _dns_egress_policy(_objects())["spec"]["egress"][0]
    destinations = rule["to"]
    assert len(destinations) == 1
    destination = destinations[0]
    assert destination.get("namespaceSelector", {}).get("matchLabels") == {
        "kubernetes.io/metadata.name": "kube-system"
    }
    # The load-bearing regression: no podSelector alongside the
    # namespaceSelector. Reintroducing one reproduces the exact defect
    # this fix corrects (Service-ClusterIP DNS resolution silently
    # breaking under a real, enforced Dataplane V2 policy).
    assert "podSelector" not in destination


def test_dns_egress_allows_only_dns_ports() -> None:
    ports = _dns_egress_policy(_objects())["spec"]["egress"][0]["ports"]
    assert {(port["protocol"], port["port"]) for port in ports} == {("UDP", 53), ("TCP", 53)}


def test_dns_egress_has_no_ipblock_or_wildcard_destination() -> None:
    """The failed remediation attempts (a literal kube-dns ClusterIP
    ipBlock, and an unrestricted 0.0.0.0/0 diagnostic) must never be
    committed -- both were empirically proven non-functional on the real
    cluster, and 0.0.0.0/0 would additionally be a real security
    regression (arbitrary external DNS egress) if it ever did work."""
    policy = _dns_egress_policy(_objects())
    rendered = yaml.safe_dump(policy)
    assert "ipBlock" not in rendered
    assert "0.0.0.0/0" not in rendered
    for destination in policy["spec"]["egress"][0]["to"]:
        assert "ipBlock" not in destination


def test_dns_egress_rule_is_single_and_self_contained() -> None:
    """No second egress entry (e.g. a leftover ClusterIP-specific rule)
    was left alongside the namespaceSelector fix."""
    egress = _dns_egress_policy(_objects())["spec"]["egress"]
    assert len(egress) == 1


def test_dns_egress_does_not_broaden_other_network_policies() -> None:
    """The DNS fix touches emg-dns-egress only -- every other policy's
    selectors/rules are unchanged from the already-qualified model."""
    policies = {
        obj["metadata"]["name"]: obj for obj in _objects() if obj["kind"] == "NetworkPolicy"
    }
    default_deny = policies["emg-default-deny"]["spec"]
    assert default_deny["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/part-of": "emg-platform"
    }
    assert "ingress" not in default_deny and "egress" not in default_deny
    dns_policy_spec = policies["emg-dns-egress"]["spec"]
    assert dns_policy_spec["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/part-of": "emg-platform"
    }


def test_authority_to_signer_restriction_unchanged_by_dns_fix() -> None:
    """Item: the authority<->signer boundary is untouched by the DNS
    remediation -- re-asserts the same invariant as
    test_recovery_signer_network_policy_still_restricted_to_authority_only
    to make the DNS-fix commit's blast radius explicit and independently
    verifiable."""
    policies = {
        obj["metadata"]["name"]: obj for obj in _objects() if obj["kind"] == "NetworkPolicy"
    }
    signer_ingress = policies["emg-recovery-signer-ingress"]["spec"]["ingress"][0]
    assert signer_ingress["from"] == [
        {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "emg-recovery-authority"}}}
    ]
    authority_egress = policies["emg-recovery-authority-to-signer-egress"]["spec"]["egress"][0]
    assert authority_egress["to"] == [
        {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "emg-recovery-signer"}}}
    ]


def test_dns_egress_consistent_across_staging_and_production() -> None:
    staging_policy = _dns_egress_policy(_staging_objects())
    production_policy = _dns_egress_policy(_objects())
    assert staging_policy["spec"] == production_policy["spec"]
