"""Command-line entrypoint for ADR-041 one-shot database Jobs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .database import (
    bootstrap_database_roles,
    reconcile_identity_recovery,
    retry_dirty_audit_v001,
    retry_dirty_knowledge_graph_v005,
    run_audit_migrations,
    run_identity_migrations,
    validate_provisioned_databases,
)
from .recovery_evidence import (
    CniQualificationEvidenceDenied,
    SessionFenceEvidenceDenied,
    terminate_and_prove_identity_app_sessions_excluded,
    validate_cni_egress_qualification_evidence,
    validate_session_fence_evidence,
)
from .recovery_fence import RecoveryFenceEvidenceDenied, validate_recovery_fence_evidence


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable {name} is missing")
    return value


def _optional_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value else default


def main() -> None:
    parser = argparse.ArgumentParser(description="ADR-041 database provisioning")
    parser.add_argument(
        "command",
        choices=(
            "database-bootstrap",
            "audit-migrate",
            "audit-retry-v001",
            "identity-migrate",
            "identity-reconcile",
            "identity-session-fence",
            "knowledge-graph-retry-v005",
            "validate-database",
            "validate-recovery-fence",
            "validate-recovery-qualification",
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
                "emg_knowledge_graph_migrator": _required(
                    "EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN"
                ),
                "emg_knowledge_graph_app": _required("EMG_KNOWLEDGE_GRAPH_API_POSTGRES_DSN"),
                "emg_identity_migrator": _required("EMG_IDENTITY_MIGRATION_POSTGRES_DSN"),
                "emg_identity_app": _required("EMG_IDENTITY_REFRESH_TOKEN_POSTGRES_DSN"),
            },
        )
    elif args.command == "audit-migrate":
        run_audit_migrations(_required("EMG_AUDIT_MIGRATION_POSTGRES_DSN"))
    elif args.command == "audit-retry-v001":
        retry_dirty_audit_v001(_required("EMG_AUDIT_MIGRATION_POSTGRES_DSN"))
    elif args.command == "identity-migrate":
        run_identity_migrations(_required("EMG_IDENTITY_MIGRATION_POSTGRES_DSN"))
    elif args.command == "identity-reconcile":
        # A6/A9: reconciliation runs only after the governed fencing protocol
        # (A9.2-A9.5) has produced its required positive evidence and the
        # external authority has already been rotated (A3.2); this command
        # performs only the PostgreSQL transaction itself.
        reconcile_identity_recovery(
            _required("EMG_IDENTITY_MIGRATION_POSTGRES_DSN"),
            _required("EMG_IDENTITY_RECOVERY_GENERATION"),
            _required("EMG_IDENTITY_RECOVERY_AUTHORITY_REVISION"),
        )
    elif args.command == "identity-session-fence":
        # A9.3: terminates and re-proves the absence of surviving
        # emg_identity_app sessions against the recovery target, using the
        # governed database-bootstrap-administrator credential (never
        # emg_identity_app or emg_identity_migrator -- see
        # recovery_evidence.py for why). Writes evidence only on success.
        try:
            terminate_and_prove_identity_app_sessions_excluded(
                _required("EMG_DATABASE_BOOTSTRAP_ADMIN_DSN"),
                target_environment=_required("EMG_IDENTITY_RECOVERY_TARGET_ENVIRONMENT"),
                verified_by=_required("EMG_IDENTITY_RECOVERY_FENCE_ACTOR"),
                evidence_output=Path(_required("EMG_IDENTITY_SESSION_FENCE_EVIDENCE")),
            )
        except SessionFenceEvidenceDenied as exc:
            raise SystemExit(f"database-session fence denied: {exc}") from exc
    elif args.command == "knowledge-graph-retry-v005":
        retry_dirty_knowledge_graph_v005(_required("EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN"))
    elif args.command == "validate-database":
        # Normal deployment mode: no recovery is occurring, so no A9 fence
        # evidence is required or consulted.
        validate_provisioned_databases(
            _required("EMG_AUDIT_MIGRATION_POSTGRES_DSN"),
            _required("EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN"),
            _required("EMG_IDENTITY_MIGRATION_POSTGRES_DSN"),
        )
    elif args.command == "validate-recovery-fence":
        # ADR-043 Amendment 1 A9.4/A9.6: standalone fail-closed gate
        # consulted by the recovery coordinator before advancing past a
        # single network-fence phase transition. Never mutates network
        # state; see recovery_fence.py.
        try:
            validate_recovery_fence_evidence(
                Path(_required("EMG_IDENTITY_RECOVERY_FENCE_EVIDENCE")),
                expected_phase=_required("EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_PHASE"),
                expected_target_environment=_required(
                    "EMG_IDENTITY_RECOVERY_FENCE_TARGET_ENVIRONMENT"
                ),
                max_age_seconds=_optional_float(
                    "EMG_IDENTITY_RECOVERY_FENCE_MAX_AGE_SECONDS", 900.0
                ),
            )
        except RecoveryFenceEvidenceDenied as exc:
            raise SystemExit(f"recovery network fence evidence denied: {exc}") from exc
    else:
        # ADR-043 Amendment 1 A11: Stage-50 RECOVERY-QUALIFICATION mode.
        # Distinct from "validate-database" above (normal deployment mode,
        # which never requires or consults recovery evidence): this command
        # additionally requires and validates the A9 network-fence,
        # database-session-fence, and CNI-egress-qualification positive
        # evidence records for the recovery being validated, all bound to the
        # same EMG_IDENTITY_RECOVERY_TARGET_ENVIRONMENT. Every environment
        # variable below is mandatory -- there is no silent fallback to
        # normal mode, and database validation still runs in full.
        #
        # Round-3 remediation: A11 requires Stage-50 to confirm the A9
        # evidence records are "attributable to the fence owner for the
        # recovery being validated," not merely present. The expected owner
        # and namespace come only from this command's own required inputs
        # (the recovery coordinator's invocation) -- never inferred from the
        # evidence files themselves, which are untrusted until checked
        # against these values. The same expected owner is required of every
        # A9 evidence type in this recovery: this repository defines no
        # distinct "CNI verifier" role separate from the fence owner (see
        # recovery_evidence.py).
        validate_provisioned_databases(
            _required("EMG_AUDIT_MIGRATION_POSTGRES_DSN"),
            _required("EMG_KNOWLEDGE_GRAPH_MIGRATION_POSTGRES_DSN"),
            _required("EMG_IDENTITY_MIGRATION_POSTGRES_DSN"),
        )
        target_environment = _required("EMG_IDENTITY_RECOVERY_TARGET_ENVIRONMENT")
        expected_owner = _required("EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER")
        expected_namespace = _required("EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE")
        try:
            validate_recovery_fence_evidence(
                Path(_required("EMG_IDENTITY_RECOVERY_FENCE_EVIDENCE")),
                expected_phase=_required("EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_PHASE"),
                expected_target_environment=target_environment,
                expected_namespace=expected_namespace,
                expected_owner=expected_owner,
            )
            validate_session_fence_evidence(
                Path(_required("EMG_IDENTITY_SESSION_FENCE_EVIDENCE")),
                expected_target_environment=target_environment,
                expected_owner=expected_owner,
            )
            validate_cni_egress_qualification_evidence(
                Path(_required("EMG_IDENTITY_CNI_QUALIFICATION_EVIDENCE")),
                expected_target_environment=target_environment,
                expected_cluster_identifier=_required("EMG_IDENTITY_CNI_QUALIFICATION_CLUSTER"),
                expected_owner=expected_owner,
            )
        except (
            RecoveryFenceEvidenceDenied,
            SessionFenceEvidenceDenied,
            CniQualificationEvidenceDenied,
        ) as exc:
            raise SystemExit(f"Stage-50 recovery qualification denied: {exc}") from exc


if __name__ == "__main__":
    main()
