# Audit and Logging

## Purpose
To maintain a tamper-resistant record of platform events.

## Scope
Audit event pipeline and custody ledger.

## Repository Evidence
- `services/audit/`: authenticated Audit Service with PostgreSQL persistence.
- `services/audit-projector/`: ADR-028 mutation-dispatch consumer.
- `services/audit-projector/tests/integration/test_authoritative_audit_e2e.py`:
  complete mutation-to-audit PostgreSQL reconciliation proof.
- `libs/python/emg-persistence/src/emg_persistence/migrations/postgres/`
  V007/V008: projector privileges and EL-10 evidence-ledger hardening.
- `libs/python/emg-persistence/src/emg_persistence/migrations/audit_postgres/`:
  canonical Audit schema migration stream.
- `infra/backup/` and `tools/backup/`: ADR-039 backup/PITR and evidence-anchor
  verification.

## Current Implementation
The Audit platform implements centralized hash-chained events, integrity
verification, custody records, authenticated append/query APIs, and
PostgreSQL-authoritative storage. The ADR-028 Audit Projector consumes
tenant-partitioned `mutation_dispatch` work and delivers immutable mutation
audit intents at least once through `POST /audit/events`. Event identity is
deterministic (`kg-mutation:{mutation_uuid}:{ordinal}`); replay after partial
delivery is expected and Audit Service idempotency suppresses duplicates.

RC-1E proves the complete real-PostgreSQL path from mutation commit through
dispatch claim, authenticated delivery, Audit persistence, recovery replay,
and backlog completion. ADR-038 delegated operations retain synchronous,
fail-closed audit attribution separately from projector delivery.

V008 implements EL-10 structural checks and an owner-binding append-only
trigger for `evidence_ledger`. Those database controls reject invalid sequence,
hash-shape, genesis, update, and delete operations. They do **not**
cryptographically recompute every entry or chain link; repository
`verify_range()` performs that verification.

## Constraints
- Delivery is at least once, never claimed as exactly once.
- Poison or exhausted dispatch work remains durable and visible.
- Audit and evidence records are never repaired or rewritten in place.
- PostgreSQL is authoritative; Neo4j is not an audit or evidence store.

## Dependencies
- `emg-audit-client`
- `emg-audit-pipeline`
- PostgreSQL

## Security Considerations
- Projector clients are tenant-scoped and must carry `service-account` and
  `svc-audit-projector` roles.
- Audit Service derives its recognized projector clients from the canonical
  ADR-041 identity inventory; no wildcard trust is permitted.
- Secret values are environment-owned and delivered through External Secret
  references; inventory contains no client secret.

## Operational Considerations
- Apply database bootstrap, Knowledge Graph/Audit migrations, Keycloak
  provisioning, and consistency validation before workload rollout.
- Monitor pending, retry-scheduled, claimed, and exhausted dispatch state.
- Use ADR-039 PITR tooling and run evidence-anchor plus chain verification after
  restore. Production scheduling/KMS/cross-region choices and witnessed
  rehearsal remain environment prerequisites.

## Open Questions
- Production observability backend, alert thresholds, retention governance,
  and accreditation remain environment/release-governance work.

## Cross References
- [Security Architecture Overview](SECURITY_ARCHITECTURE_OVERVIEW.md)
- [ADR-028 Audit Reconciliation](../architecture/EMG_ADR-028_AUDIT_RECONCILIATION.md)
- [ADR-039 Backup/PITR Governance](../architecture/EMG_ADR-039_BACKUP_PITR_AND_RECOVERY_GOVERNANCE.md)
- [ADR-041 Production Provisioning](../architecture/EMG_ADR-041_PRODUCTION_PROVISIONING_OWNERSHIP_AND_BOOTSTRAP_CONTRACT.md)

## Future Considerations
Continuous Neo4j projection, DAST, dedicated IaC scanning, and broader
post-v1 product surfaces do not alter the implemented audit/evidence contract.
