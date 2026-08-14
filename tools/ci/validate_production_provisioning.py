#!/usr/bin/env python3
"""Fail-closed static validation for the ADR-041 production contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml
from emg_common_types import parse_projector_identity_inventory
from emg_persistence.provisioning import (
    GOVERNED_DATABASE_ROLES,
    NETWORK_POLICY_NAME,
    PHASE_POD_SELECTOR_LABELS,
    policy_selects_any_identity_pod,
)

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "infra/environments/production"
REQUIRED_ROLES = {
    "emg_audit_migrator",
    "emg_audit_app",
    "emg_audit_projector",
    "emg_knowledge_graph_migrator",
    "emg_knowledge_graph_app",
    "emg_identity_migrator",
    "emg_identity_app",
}
REQUIRED_JOBS = {
    "emg-database-bootstrap": "10-database-roles",
    "emg-audit-migration": "20-postgresql-migrations",
    "emg-knowledge-graph-migration": "20-postgresql-migrations",
    "emg-identity-migration": "20-postgresql-migrations",
    "emg-keycloak-provision": "30-keycloak-projector-clients",
    "emg-provisioning-validate": "50-consistency-validation",
}


class ProvisioningValidationError(RuntimeError):
    """Production manifests do not satisfy ADR-041."""


def _rendered_objects() -> list[dict]:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(OVERLAY)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [document for document in yaml.safe_load_all(rendered) if document]


def _container_env(container: dict) -> dict[str, dict]:
    return {entry["name"]: entry for entry in container.get("env", [])}


def _secret_keys(external_secret: dict) -> set[str]:
    return {entry["secretKey"] for entry in external_secret["spec"].get("data", [])}


def validate(objects: list[dict] | None = None) -> None:
    if set(GOVERNED_DATABASE_ROLES) != REQUIRED_ROLES:
        raise ProvisioningValidationError("database bootstrap role declaration is incomplete")
    objects = objects or _rendered_objects()
    jobs = {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "Job"}
    missing_jobs = set(REQUIRED_JOBS) - set(jobs)
    if missing_jobs:
        raise ProvisioningValidationError(f"missing provisioning Jobs: {sorted(missing_jobs)}")
    for name, stage in REQUIRED_JOBS.items():
        actual = jobs[name]["metadata"].get("annotations", {}).get("emg.platform/bootstrap-stage")
        if actual != stage:
            raise ProvisioningValidationError(f"{name} has invalid bootstrap stage")

    bootstrap = jobs["emg-database-bootstrap"]["spec"]["template"]["spec"]["containers"][0]
    if bootstrap.get("command") != [
        "python",
        "-m",
        "emg_persistence.provisioning",
        "database-bootstrap",
    ]:
        raise ProvisioningValidationError("database bootstrap command is missing")
    bootstrap_env = _container_env(bootstrap)
    if set(bootstrap_env) != {
        "EMG_DATABASE_BOOTSTRAP_ADMIN_DSN",
        "EMG_AUDIT_MIGRATION_POSTGRES_DSN",
        "EMG_AUDIT_POSTGRES_DSN",
        "EMG_AUDIT_PROJECTOR_POSTGRES_DSN",
        "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN",
        "EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN",
        "EMG_IDENTITY_MIGRATION_POSTGRES_DSN",
        "EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN",
    }:
        raise ProvisioningValidationError("database bootstrap credentials are incomplete")
    expected_bootstrap_wiring = {
        "EMG_DATABASE_BOOTSTRAP_ADMIN_DSN": (
            "emg-database-bootstrap-secrets",
            "admin-postgres-dsn",
        ),
        "EMG_AUDIT_MIGRATION_POSTGRES_DSN": (
            "emg-audit-secrets",
            "migration-postgres-dsn",
        ),
        "EMG_AUDIT_POSTGRES_DSN": ("emg-audit-secrets", "postgres-dsn"),
        "EMG_AUDIT_PROJECTOR_POSTGRES_DSN": (
            "emg-audit-projector-secrets",
            "postgres-dsn",
        ),
        "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN": (
            "emg-knowledge-graph-secrets",
            "migration-postgres-dsn",
        ),
        "EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN": (
            "emg-knowledge-graph-secrets",
            "postgres-dsn",
        ),
        "EMG_IDENTITY_MIGRATION_POSTGRES_DSN": (
            "emg-identity-secrets",
            "migration-postgres-dsn",
        ),
        "EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN": (
            "emg-identity-secrets",
            "refresh-postgres-dsn",
        ),
    }
    for name, (secret, key) in expected_bootstrap_wiring.items():
        if bootstrap_env[name] != {
            "name": name,
            "valueFrom": {"secretKeyRef": {"name": secret, "key": key}},
        }:
            raise ProvisioningValidationError(
                f"database bootstrap credential wiring is invalid: {name}"
            )

    audit_migration = jobs["emg-audit-migration"]["spec"]["template"]["spec"]["containers"][0]
    if audit_migration.get("command", [])[-1:] != ["audit-migrate"]:
        raise ProvisioningValidationError("Audit migration command is missing")
    identity_migration = jobs["emg-identity-migration"]["spec"]["template"]["spec"]["containers"][0]
    if identity_migration.get("command", [])[-1:] != ["identity-migrate"]:
        raise ProvisioningValidationError("Identity migration command is missing")
    if set(_container_env(identity_migration)) != {"EMG_IDENTITY_MIGRATION_POSTGRES_DSN"}:
        raise ProvisioningValidationError("Identity migration credential boundary is invalid")

    v007 = (
        ROOT
        / "libs/python/emg-persistence/src/emg_persistence/migrations/postgres"
        / "V007__audit_projector_privileges.sql"
    ).read_text(encoding="utf-8")
    if "CREATE ROLE" in v007:
        raise ProvisioningValidationError("V007 role boundary is invalid")
    audit_stream = (
        ROOT
        / "libs/python/emg-persistence/src/emg_persistence/migrations/audit_postgres"
        / "V001__audit_schema.sql"
    )
    if not audit_stream.is_file() or "tools/seed-data" in audit_migration.get("command", []):
        raise ProvisioningValidationError("canonical Audit migration stream is missing")
    identity_stream = (
        ROOT
        / "libs/python/emg-persistence/src/emg_persistence/migrations/identity_postgres"
        / "V001__identity_refresh_state.sql"
    )
    if not identity_stream.is_file() or "tools/seed-data" in identity_migration.get("command", []):
        raise ProvisioningValidationError("canonical Identity migration stream is missing")
    identity_seed = ROOT / "tools/seed-data/postgres/007_identity_refresh_tokens.sql"
    seed_text = identity_seed.read_text(encoding="utf-8")
    if "CREATE TABLE" in seed_text or "CREATE INDEX" in seed_text:
        raise ProvisioningValidationError("local Identity seed remains a structural authority")

    external_secrets = {
        obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "ExternalSecret"
    }
    required_secret_keys = {
        "emg-database-bootstrap-secrets": {"admin-postgres-dsn"},
        "emg-audit-secrets": {"postgres-dsn", "migration-postgres-dsn"},
        "emg-identity-secrets": {"refresh-postgres-dsn", "migration-postgres-dsn"},
        "emg-audit-projector-secrets": {
            "postgres-dsn",
            "identity-inventory-json",
            "tenant-credentials-json",
        },
        "emg-knowledge-graph-secrets": {"postgres-dsn", "migration-postgres-dsn"},
        "emg-keycloak-provision-secrets": {"admin-username", "admin-password"},
    }
    for name, keys in required_secret_keys.items():
        if name not in external_secrets or not keys.issubset(_secret_keys(external_secrets[name])):
            raise ProvisioningValidationError(f"required External Secret wiring is missing: {name}")
    if "audit-client-ids" in _secret_keys(external_secrets["emg-audit-projector-secrets"]):
        raise ProvisioningValidationError("independent Audit projector allow-list is forbidden")

    deployments = {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "Deployment"}
    identity_stage = (
        deployments["emg-identity"]["metadata"]
        .get("annotations", {})
        .get("emg.platform/bootstrap-stage")
    )
    if identity_stage != "60-identity-service":
        raise ProvisioningValidationError("Identity serving stage is not ordered after validation")
    validation_env = _container_env(
        jobs["emg-provisioning-validate"]["spec"]["template"]["spec"]["containers"][0]
    )
    if set(validation_env) != {
        "EMG_AUDIT_MIGRATION_POSTGRES_DSN",
        "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN",
        "EMG_IDENTITY_MIGRATION_POSTGRES_DSN",
    }:
        raise ProvisioningValidationError("Stage-50 database validation credentials are incomplete")
    audit_env = _container_env(
        deployments["emg-audit"]["spec"]["template"]["spec"]["containers"][0]
    )
    projector_env = _container_env(
        deployments["emg-audit-projector"]["spec"]["template"]["spec"]["containers"][0]
    )
    if "EMG_AUDIT_PROJECTOR_CLIENT_IDS" in audit_env:
        raise ProvisioningValidationError("Audit contains an independent projector allow-list")
    if "EMG_AUDIT_PROJECTOR_IDENTITY_INVENTORY_JSON" not in audit_env:
        raise ProvisioningValidationError("Audit identity inventory wiring is missing")
    if not {
        "EMG_AUDIT_PROJECTOR_IDENTITY_INVENTORY_JSON",
        "EMG_AUDIT_PROJECTOR_TENANT_CREDENTIALS_JSON",
    }.issubset(projector_env):
        raise ProvisioningValidationError("Projector inventory/credential wiring is incomplete")

    keycloak_env = _container_env(
        jobs["emg-keycloak-provision"]["spec"]["template"]["spec"]["containers"][0]
    )
    if not {
        "EMG_PROJECTOR_IDENTITY_INVENTORY_JSON",
        "EMG_AUDIT_PROJECTOR_TENANT_CREDENTIALS_JSON",
    }.issubset(keycloak_env):
        raise ProvisioningValidationError("Keycloak projector identity wiring is incomplete")

    example = (ROOT / "infra/provisioning/projector-identities.example.json").read_text(
        encoding="utf-8"
    )
    parse_projector_identity_inventory(example, reject_placeholders=False)
    schema = json.loads(
        (ROOT / "infra/provisioning/projector-identities.schema.json").read_text(encoding="utf-8")
    )
    if schema.get("properties", {}).get("projector_identities", {}).get("minItems") != 1:
        raise ProvisioningValidationError("projector identity schema does not fail closed")

    _validate_identity_recovery_fence(objects)


def _validate_identity_recovery_fence(objects: list[dict]) -> None:
    """ADR-043 Amendment 1 A9.4/A9.6: static, repository-owned half of the
    fence-evidence gate. Does not and cannot verify live network state (that
    is environment-owned, see infra/environments/production/README.md's
    "Network boundary" section); proves instead that the recovery-qualification
    workload structurally cannot become client-routable, and that the three
    phase-scoped NetworkPolicy templates a real recovery event must apply are
    each present and scoped to the exact governed label set -- so drift
    between the templates and the PHASE_POD_SELECTOR_LABELS contract
    tools/backup/identity-recovery-fence.sh and validate-recovery-fence
    enforce at recovery time is caught here, before any recovery is attempted.
    """

    deployments = {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "Deployment"}
    services = {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "Service"}
    qualify = deployments.get("emg-identity-recovery-qualify")
    if qualify is None:
        raise ProvisioningValidationError("Identity recovery-qualification workload is missing")
    if qualify["spec"].get("replicas") != 0:
        raise ProvisioningValidationError(
            "Identity recovery-qualification workload must default to zero replicas"
        )
    if (
        qualify["metadata"].get("annotations", {}).get("emg.platform/bootstrap-stage")
        != "recovery-only"
    ):
        raise ProvisioningValidationError(
            "Identity recovery-qualification workload must not join the ordinary stage sequence"
        )
    qualify_labels = qualify["spec"]["template"]["metadata"]["labels"]
    if qualify_labels.get("app.kubernetes.io/name") != "emg-identity-recovery-qualify":
        raise ProvisioningValidationError(
            "Identity recovery-qualification workload has the wrong pod label"
        )
    for name, service in services.items():
        selector = service["spec"].get("selector", {})
        if all(qualify_labels.get(key) == value for key, value in selector.items()) and selector:
            raise ProvisioningValidationError(
                f"Service {name} would route to the Identity recovery-qualification "
                "workload; A9.4 Phase 2 requires it to be unreachable from any Service"
            )

    overlay = ROOT / "infra/environments/production"
    for phase, expected_labels in PHASE_POD_SELECTOR_LABELS.items():
        template_path = overlay / f"identity-db-egress.{phase}.example.yaml"
        if not template_path.is_file():
            raise ProvisioningValidationError(f"missing recovery network fence template: {phase}")
        document = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        if document.get("kind") != "NetworkPolicy":
            raise ProvisioningValidationError(f"recovery network fence template {phase} is invalid")
        if document["metadata"]["name"] != "emg-identity-db-egress":
            raise ProvisioningValidationError(
                f"recovery network fence template {phase} names the wrong object"
            )
        selector = document["spec"]["podSelector"]
        labels = set(selector.get("matchLabels", {}).values())
        for expr in selector.get("matchExpressions", []):
            if expr.get("key") == "app.kubernetes.io/name" and expr.get("operator") == "In":
                labels.update(expr.get("values", []))
        if labels != set(expected_labels):
            raise ProvisioningValidationError(
                f"recovery network fence template {phase} podSelector does not match "
                "the governed PHASE_POD_SELECTOR_LABELS contract"
            )
        if document["spec"].get("policyTypes") != ["Egress"]:
            raise ProvisioningValidationError(
                f"recovery network fence template {phase} must be Egress-only"
            )

    _validate_non_identity_db_egress_templates(overlay)
    _validate_recovery_qualification_job(objects)


#: Round-2 remediation (independent review found the broad
#: external-egress.example.yaml selector additively defeated the Identity
#: phase fence): every other workload that needs PostgreSQL reachability gets
#: its own dedicated, workload-scoped template, named here so this validator
#: can prove each one exists, is Egress-only, and is scoped to exactly its
#: own workload -- never to any Identity label.
NON_IDENTITY_DB_EGRESS_TEMPLATES: dict[str, tuple[str, ...]] = {
    "audit-db-egress.example.yaml": ("emg-audit", "emg-audit-migration"),
    "audit-projector-db-egress.example.yaml": ("emg-audit-projector",),
    "knowledge-graph-db-egress.example.yaml": (
        "emg-knowledge-graph",
        "emg-knowledge-graph-migration",
    ),
    "provisioning-db-egress.example.yaml": (
        "emg-database-bootstrap",
        "emg-provisioning-validate",
    ),
}


def _validate_non_identity_db_egress_templates(overlay: Path) -> None:
    """Round-2 remediation: (1) every non-Identity workload that needs
    PostgreSQL reachability has its own dedicated template, correctly scoped;
    (2) no ``.example.yaml`` NetworkPolicy template in this overlay -- not
    just the ones this function already knows the name of -- selects any
    Identity-owned pod, using the same full-label-set selector evaluation
    :func:`emg_persistence.provisioning.detect_additive_identity_bypass` uses
    live against the cluster. This is the static, checked-in-repository half
    of that same invariant: it cannot see what CIDR/port an operator fills
    in, but it can and does prove the *selector* structure can never grant
    Identity-labeled pods PostgreSQL reachability through any file other than
    the three identity-db-egress.*.example.yaml templates.
    """

    for filename, expected_workloads in NON_IDENTITY_DB_EGRESS_TEMPLATES.items():
        template_path = overlay / filename
        if not template_path.is_file():
            raise ProvisioningValidationError(f"missing database egress template: {filename}")
        document = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        if document.get("kind") != "NetworkPolicy":
            raise ProvisioningValidationError(f"database egress template {filename} is invalid")
        if document["spec"].get("policyTypes") != ["Egress"]:
            raise ProvisioningValidationError(
                f"database egress template {filename} must be Egress-only"
            )
        selector = document["spec"]["podSelector"]
        labels = set(selector.get("matchLabels", {}).values())
        for expr in selector.get("matchExpressions", []):
            if expr.get("key") == "app.kubernetes.io/name" and expr.get("operator") == "In":
                labels.update(expr.get("values", []))
        if labels != set(expected_workloads):
            raise ProvisioningValidationError(
                f"database egress template {filename} podSelector does not match "
                f"its governed workload set {sorted(expected_workloads)}"
            )
        if policy_selects_any_identity_pod(document["spec"]):
            raise ProvisioningValidationError(
                f"database egress template {filename} selector unexpectedly "
                "matches an Identity-owned pod -- additive policy bypass"
            )

    # A broad, genuinely shared template (external-egress.example.yaml) is
    # legitimately allowed to select Identity-owned pods -- Identity needs
    # Keycloak/backup-repository reachability like every other workload, and
    # that is not the defect. What must never happen is that template
    # shipping with actual egress *content* while its selector also reaches
    # an Identity pod, since this repository cannot know at checked-in time
    # whether an operator will later add the shared PostgreSQL CIDR to it
    # (detect_additive_identity_bypass is the live check that catches that
    # once a real CIDR exists). Two invariants are checked statically
    # instead, for every Egress NetworkPolicy template in this overlay other
    # than the three identity-db-egress ones: it must never reuse the
    # governed emg-identity-db-egress object name, and if its selector
    # matches an Identity pod, its checked-in egress content must be empty.
    identity_only_template_names = {
        f"identity-db-egress.{phase}.example.yaml" for phase in PHASE_POD_SELECTOR_LABELS
    }
    for template_path in sorted(overlay.glob("*.example.yaml")):
        if template_path.name in identity_only_template_names:
            continue
        document = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        if document.get("kind") != "NetworkPolicy" or "Egress" not in (
            document.get("spec", {}).get("policyTypes") or []
        ):
            continue
        if document["metadata"].get("name") == NETWORK_POLICY_NAME:
            raise ProvisioningValidationError(
                f"{template_path.name} reuses the governed emg-identity-db-egress "
                "object name outside the identity-db-egress.*.example.yaml family"
            )
        spec = document.get("spec", {})
        if policy_selects_any_identity_pod(spec) and (spec.get("egress") or []):
            raise ProvisioningValidationError(
                f"{template_path.name} selects an Identity-owned pod and ships with "
                "non-empty egress content in the repository -- this file must never "
                "carry a resolved CIDR (fill in and apply it as its own copy outside "
                "the repository if it legitimately needs one)"
            )


def _validate_recovery_qualification_job(objects: list[dict]) -> None:
    """ADR-043 Amendment 1 A11: Stage-50 recovery-qualification mode is a
    distinct, on-demand Job, never part of the ordinary 10-70 stage sequence
    (so normal deployment never requires or consults recovery evidence), and
    it must run the recovery-qualification command, never the ordinary
    validate-database command silently substituted for it.
    """

    jobs = {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "Job"}
    recovery_job = jobs.get("emg-provisioning-validate-recovery")
    if recovery_job is None:
        raise ProvisioningValidationError("Stage-50 recovery-qualification Job is missing")
    if (
        recovery_job["metadata"].get("annotations", {}).get("emg.platform/bootstrap-stage")
        != "recovery-only"
    ):
        raise ProvisioningValidationError(
            "Stage-50 recovery-qualification Job must not join the ordinary stage sequence"
        )
    container = recovery_job["spec"]["template"]["spec"]["containers"][0]
    if container.get("command", [])[-1:] != ["validate-recovery-qualification"]:
        raise ProvisioningValidationError(
            "Stage-50 recovery-qualification Job does not run recovery-qualification mode"
        )
    recovery_env = _container_env(container)
    if not {
        "EMG_IDENTITY_RECOVERY_FENCE_EVIDENCE",
        "EMG_IDENTITY_SESSION_FENCE_EVIDENCE",
        "EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE",
    }.issubset(recovery_env):
        raise ProvisioningValidationError(
            "Stage-50 recovery-qualification Job is missing required A9 evidence wiring"
        )
    # A11 (round-3 remediation): attribution and namespace binding are only as
    # strong as the CLI actually being given something to compare evidence
    # against -- a manifest that dropped these inputs would silently regress
    # Stage-50 back to presence-only "verified_by" checking.
    if not {
        "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER",
        "EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE",
    }.issubset(recovery_env):
        raise ProvisioningValidationError(
            "Stage-50 recovery-qualification Job is missing required A11 expected "
            "owner/namespace wiring"
        )


def main() -> None:
    validate()
    print("ADR-041 production provisioning contract: valid")


if __name__ == "__main__":
    main()
