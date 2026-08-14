# EMG v1 documentation index

**Repository status:** COMPLETE
**Live qualification status:** PENDING_LIVE
**GA status:** NOT CLAIMED

This is the audience-oriented entry point for the implemented EMG v1 system. Historical plans,
sprint records, and proposed ADRs remain useful context but do not override accepted ADRs,
executable configuration, or this index.

## Start here

| Audience | Primary document |
| --- | --- |
| Executive and release authority | `docs/executive/EXECUTIVE_SUMMARY.md`; `docs/release/EMG_V1_RC8_PARALLEL_COMPLETION_REVIEW.md` |
| Studio user | `docs/v1/USER_GUIDE.md` |
| System administrator / operator | `docs/v1/ADMIN_OPERATIONS_GUIDE.md` |
| Incident responder | `docs/v1/TROUBLESHOOTING_AND_MAINTENANCE.md`; `docs/v1/SUPPORT_AND_ESCALATION.md` |
| Security operator | `docs/v1/SECURITY_OPERATIONS_GUIDE.md` |
| Developer / reviewer | `docs/v1/ENGINEERING_HANDBOOK.md` |
| API consumer | `docs/v1/API_COOKBOOK.md` |
| Release operator | `docs/operations/release-promotion-and-rollback.md`; `docs/release/EMG_V1_RC9_PREPARATION_AND_CLAUDE_RECONCILIATION.md` |

## Authoritative supporting records

- Architecture: `docs/architecture/EMG_Architecture_Baseline_v1.0_Final.md` and
  `docs/architecture/EMG_ARCHITECTURE_DECISION_REGISTER.md`.
- Product scope: `docs/product/EMG_PD-001_MVP_FREEZE_CONTROL_RECORD.md`.
- Deployment: `docs/devops/PRODUCTION_DEPLOYMENT_GUIDE.md` and environment overlay READMEs.
- Recovery: `docs/operations/postgresql-backup-recovery.md`.
- Monitoring: `observability/README.md` and `docs/operations/alert-runbook.md`.
- Supply chain: ADR-040 and `docs/devops/ARTIFACT_MANAGEMENT.md`.

## V1 capability boundary

V1 implements authenticated Studio access, governed entity search and exploration, Knowledge Graph
read/mutation APIs, PostgreSQL authority, Neo4j projection, authorization/classification, delegated
human identity, a durable Identity refresh-token database with fail-closed recovery governance
(isolated migration stream, recovery-state gate, two-phase network fence, database-session fence,
and Stage-50 recovery qualification), Audit and Audit Projector, governed provisioning,
observability artifacts, backup and PITR tooling, and immutable runtime-image release tooling.

The `/decisions`, `/evidence`, and `/timeline` Studio routes are planned placeholders, not complete
product workspaces. AI orchestration, broad ingestion, the proposed enterprise API program, full
Decision Intelligence, and the unresolved standalone entity-resolution package are POST_V1.

## Evidence rule

`PENDING_LIVE` means repository contracts exist but target execution has not been accepted here.
Never convert it to PASS from screenshots, recollection, local mocks, or RC.8 evidence copied to a
different source commit. Evidence must identify the release manifest, resolved bundle, environment,
workflow/run where applicable, timestamp, result, and accountable witness role without retaining
secrets or tokens.
