# EMG v1 support ownership and escalation

Named people and contact channels are environment-owned and therefore `PENDING_LIVE`. The role
matrix below is mandatory; activation must bind each role to an accountable person or on-call
group before production promotion.

| Domain | Primary role | Escalate when | Required secondary role |
| --- | --- | --- | --- |
| Studio and Studio BFF | Application owner | Login/session/CSRF/UI boundary fails | Identity or Security |
| Identity and Keycloak | Identity owner | Issuer/client/claim/delegation failure | Security custodian |
| Knowledge Graph/search/projection | Knowledge Graph owner | Revision, search, cursor, projection or disclosure risk | Database/Security |
| Audit and Audit Projector | Audit owner | Delivery backlog, attribution, custody or integrity failure | Security/Incident commander |
| PostgreSQL/Neo4j | Database owner | Availability, privilege, migration, corruption or capacity issue | Recovery/Release authority |
| Identity recovery governance (ADR-043 fencing/reconciliation) | Recovery coordinator (single accountable actor for every fence, per A9.1) | Recovery-authority pair mismatch, fence-evidence failure, Stage-50 recovery-qualification denial | Identity owner + Security custodian |
| Kubernetes/network/TLS | Platform owner | Scheduling, ingress, egress, NetworkPolicy or certificate issue | Security/Identity as applicable |
| Monitoring and alert delivery | Observability owner | Scrape, rule evaluation, routing or receiver failure | Incident commander |
| Backup/restore/PITR | Recovery operator | Backup/WAL gap, custody loss, failed restore or missed RPO/RTO | Security custodian + witness |
| Images/SBOM/signing/provenance | Release engineer | Scan, digest, signature, provenance or evidence mismatch | Security + Release authority |

## Severity

- **P0:** suspected tenant/classification disclosure, credential compromise, Audit/integrity loss,
  unrecoverable authoritative data, invalid promotion evidence, or production-wide unavailability.
  Stop promotion/change activity and engage Incident Commander and Security immediately.
- **P1:** major capability unavailable, recovery window at risk, sustained projector/projection
  divergence, alert delivery unavailable, or rollback unavailable. Engage domain owner and release
  authority immediately.
- **P2:** degraded but bounded behavior with safe workaround and no security/integrity risk.
- **POST_V1:** approved enhancement outside frozen scope.

## Activation fields

Before promotion record: service desk/contact route, incident commander rotation, Security
custodian, database/platform/identity owners, recovery operator, alert receiver, release authority,
business owner, after-hours path, evidence repository, and communication/status channel. Until
populated and approved, support ownership status is `PENDING_LIVE`.
