"""Import and dispatch-smoke the audit-projector image's ADR-041 entrypoints."""

from __future__ import annotations

import os
import sys

import emg_audit_projector.main  # noqa: F401
import emg_persistence.provisioning.__main__ as provisioning


def _run(command: str) -> None:
    calls: list[str] = []
    provisioning.bootstrap_database_roles = lambda *_args: calls.append("database-bootstrap")
    provisioning.run_audit_migrations = lambda *_args: calls.append("audit-migrate")
    provisioning.retry_dirty_audit_v001 = lambda *_args: calls.append("audit-retry-v001")
    provisioning.retry_dirty_knowledge_graph_v005 = lambda *_args: calls.append(
        "knowledge-graph-retry-v005"
    )
    provisioning.validate_provisioned_databases = lambda *_args: calls.append("validate-database")
    os.environ.update(
        {
            "EMG_DATABASE_BOOTSTRAP_ADMIN_DSN": "postgresql://smoke",
            "EMG_AUDIT_MIGRATION_POSTGRES_DSN": "postgresql://smoke",
            "EMG_AUDIT_POSTGRES_DSN": "postgresql://smoke",
            "EMG_AUDIT_PROJECTOR_POSTGRES_DSN": "postgresql://smoke",
            "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN": "postgresql://smoke",
            "EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN": "postgresql://smoke",
        }
    )
    sys.argv = ["emg-persistence-provisioning", command]
    provisioning.main()
    if calls != [command]:
        raise RuntimeError(f"{command} did not dispatch correctly: {calls}")


for provisioning_command in (
    "database-bootstrap",
    "audit-migrate",
    "audit-retry-v001",
    "knowledge-graph-retry-v005",
    "validate-database",
):
    _run(provisioning_command)

print("audit-projector and ADR-041 provisioning import/dispatch smoke passed")
