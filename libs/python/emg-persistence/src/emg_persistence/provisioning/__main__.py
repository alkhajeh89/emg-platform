"""Command-line entrypoint for ADR-041 one-shot database Jobs."""

from __future__ import annotations

import argparse
import os

from .database import (
    bootstrap_database_roles,
    retry_dirty_audit_v001,
    run_audit_migrations,
    validate_provisioned_databases,
)


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable {name} is missing")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="ADR-041 database provisioning")
    parser.add_argument(
        "command",
        choices=(
            "database-bootstrap",
            "audit-migrate",
            "audit-retry-v001",
            "validate-database",
        ),
    )
    args = parser.parse_args()
    if args.command == "database-bootstrap":
        bootstrap_database_roles(
            _required("EMG_DATABASE_BOOTSTRAP_ADMIN_DSN"),
            {
                "emg_audit_migrator": _required("EMG_AUDIT_MIGRATION_POSTGRES_DSN"),
                "emg_audit_app": _required("EMG_AUDIT_POSTGRES_DSN"),
                "emg_audit_projector": _required("EMG_AUDIT_PROJECTOR_POSTGRES_DSN"),
            },
        )
    elif args.command == "audit-migrate":
        run_audit_migrations(_required("EMG_AUDIT_MIGRATION_POSTGRES_DSN"))
    elif args.command == "audit-retry-v001":
        retry_dirty_audit_v001(_required("EMG_AUDIT_MIGRATION_POSTGRES_DSN"))
    else:
        validate_provisioned_databases(
            _required("EMG_AUDIT_MIGRATION_POSTGRES_DSN"),
            _required("EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN"),
        )


if __name__ == "__main__":
    main()
