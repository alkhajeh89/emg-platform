# EMG v1 troubleshooting, failure modes, and repair

## First-response discipline

1. Identify release manifest, environment, component, timestamp, correlation ID, and symptom.
2. Preserve logs and evidence without tokens, cookies, passwords, DSNs, raw queries, or payloads.
3. Check readiness and dependency health before restarting anything.
4. Prefer bounded replay/reconciliation mechanisms; never edit authoritative rows or roles by hand.
5. Escalate security or integrity failures immediately and stop promotion.

## Failure matrix

| Failure | Expected safe behavior | Repair path | Escalation |
| --- | --- | --- | --- |
| Keycloak unavailable or token invalid | Login/delegation fails closed | Restore identity dependency; verify issuer, audience, claims and clocks | Identity + Security |
| BFF session store restart | Process-local sessions may be lost | Users reauthenticate; do not reconstruct cookies | Studio/BFF owner |
| CSRF rejection | State-changing browser request denied | Reload authenticated session and retry once; never disable CSRF | Studio/BFF + Security |
| PostgreSQL unavailable | Dependent readiness fails; writes/search fail | Restore DB connectivity/pool capacity; verify no partial migration | Database owner |
| Migration dirty/checksum mismatch | Startup/deployment blocks | Stop rollout; compare exact migration set and use governed recovery | Database + Release authority |
| Cloud SQL role convergence denied | Bootstrap stops | Verify effective role attributes and admin capability; never grant cloud super-role to apps | Database + Security |
| Neo4j unavailable/divergent | Projection-dependent behavior degrades; PostgreSQL remains authority | Repair/rebuild from authoritative revision and verify hash/checkpoint | Knowledge Graph owner |
| Audit unavailable | Governed delegated operations fail or projector retries according to contract | Restore Audit; observe bounded backlog replay and idempotency | Audit owner |
| Projector backlog grows | Durable work retained; alert fires | Fix dependency/credential; resume bounded processing and verify drain | Audit Projector owner |
| Search work ceiling reached | Generic fail-closed response, no partial page/count leak | Investigate query/capacity/config; do not expose scanned/denied counts | Knowledge Graph owner |
| Search cursor invalid/expired/key unavailable | Continuation rejected | Restart search; restore only still-required key through approved custody | Knowledge Graph + Security |
| Search retention cleanup delayed | Excess retention only | Run/observe bounded later cleanup; validate cardinality/storage | Database owner |
| Backup/WAL copy fails | Recovery window at risk; alert | Restore remote custody path before retention can remove required material | Recovery + Security custodian |
| Restore integrity mismatch | Restore rejected | Preserve evidence, isolate target, investigate chain/manifest/custody | Incident commander + Security |
| Identity recovery-authority pair mismatch (restored PostgreSQL vs. materialized external authority) | Readiness and every refresh-token operation fail closed (A4/A8); no partial service | Complete the ADR-043 recovery-fencing sequence and reconciliation before any Identity traffic resumes; never patch the mismatch away | Identity + Database owner |
| Identity network/database-session fence cannot be positively verified | Recovery halts before restore or before reconciliation; fences remain closed | Re-establish and re-verify the fence from its start; never proceed on an assumed prior result | Recovery coordinator + Security custodian |
| Stage-50 recovery-qualification denies on owner/namespace attribution | Fence release blocked even after successful reconciliation | Confirm the recovery coordinator identity and namespace supplied to Stage-50 match exactly who/where performed each fence step; treat any mismatch as a process-integrity issue, not a retry | Recovery coordinator + Security custodian |
| Alert delivery fails | Monitoring P0 remains open | Repair evaluator/receiver route and re-witness fired/resolved notification | Observability owner |
| Image signature/provenance/SBOM mismatch | Publication/promotion blocked | Rebuild from approved source through governed workflow; never suppress | Release + Security |

## Restart and replay

Restarts must not be the first diagnostic action. Before a restart, capture readiness, recent
bounded logs, queue/backlog metrics, release digest, and dependency state. Afterward verify
idempotent replay, backlog reduction, projection consistency, Audit integrity, and absence of
duplicate user-visible effects.

## Maintenance constraints

- Never delete backup/WAL or cursor keys still inside a valid acceptance/recovery window.
- Never clear a dirty migration marker without following the migration-specific guard.
- Never repair Neo4j by making it the authoritative source.
- Never expose hidden result counts while diagnosing search.
- Never bypass a failed Trivy, signature, provenance, provisioning, or promotion gate.
- Never reuse staging evidence for another source commit or release manifest.
