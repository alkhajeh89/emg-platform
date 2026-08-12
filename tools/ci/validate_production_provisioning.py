#!/usr/bin/env python3
"""Fail-closed static validation for the ADR-041 production contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml
from emg_common_types import parse_projector_identity_inventory
from emg_persistence.provisioning import GOVERNED_DATABASE_ROLES

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "infra/environments/production"
REQUIRED_ROLES = {
    "emg_audit_migrator",
    "emg_audit_app",
    "emg_audit_projector",
    "emg_knowledge_graph_migrator",
    "emg_knowledge_graph_app",
}
REQUIRED_JOBS = {
    "emg-database-bootstrap": "10-database-roles",
    "emg-audit-migration": "20-postgresql-migrations",
    "emg-knowledge-graph-migration": "20-postgresql-migrations",
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

    external_secrets = {
        obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "ExternalSecret"
    }
    required_secret_keys = {
        "emg-database-bootstrap-secrets": {"admin-postgres-dsn"},
        "emg-audit-secrets": {"postgres-dsn", "migration-postgres-dsn"},
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


def main() -> None:
    validate()
    print("ADR-041 production provisioning contract: valid")


if __name__ == "__main__":
    main()
