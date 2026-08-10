# EMG V1 Operational Activation Plan

**Plan date:** 2026-08-11
**Planning baseline:** `develop` at `9e3a1839a4e2aa109af1e4229f14f7da9603041c`
**Starting P0 count:** 4
**Objective:** reduce the four operational P0 blockers to zero using the existing
approved architecture and repository controls.

## 1. Governing boundary

This is an execution plan, not authority to add product features or select vendors.
ADR-040 governs the immutable runtime-image supply chain and ADR-041 governs ordered
provisioning. ADR-015 governs observability requirements without selecting a backend.
ADR-039 and the recovery runbook govern provider-neutral backup/PITR behavior without
selecting storage or key management. ADR-035, ADR-036, ADR-038, and ADR-042 govern the
browser, BFF, delegation, and search trust chains.

The following must not be represented as live evidence: local Docker, repository
rendering, mocked token exchange, workflow syntax validation, or manually edited
`PENDING` evidence. Evidence must identify the exact release manifest and environment
where applicable, contain no secrets or raw queries, and separate machine output from
human witness approval.

## 2. Shortest activation order

1. **Resolve operational decisions and access in parallel.** Select, through the
   authorized process, the staging platform, monitoring evaluator/scraper/routing,
   remote backup repository, key/signature custody, restore host, evidence-retention
   duration, and named witnesses. Do not proceed with placeholders.
2. **Publish one exact immutable release set.** Approve a source commit, create its
   protected `v*` tag, approve the `production-release` GitHub Environment, and retain
   the workflow's manifest, resolved bundles, Trivy reports, SBOMs, signatures, and
   provenance.
3. **Instantiate and qualify real staging.** Provide staging-only secrets and external
   dependencies, verify the release set, execute ADR-041 stages, deploy the exact
   digest bundle, and establish readiness.
4. **Run three staging workstreams against the same deployed set.** In parallel where
   operators permit: activate and test the monitoring path; run authenticated browser
   and service E2E; and rehearse rollback to a distinct qualified set.
5. **Activate production recovery and alerting prerequisites.** Configure production
   WAL/backup delivery and monitoring, observe successful operation, then execute the
   isolated target-environment PITR witness and safe alert-delivery witness.
6. **Pass the promotion gate and promote.** Attach exact staging, rollback, alerting,
   recovery, and E2E evidence; obtain protected production approval; apply the already
   published production bundle in ADR-041 order; verify readiness and evidence.

This order prevents production approval before the exact candidate is deployable,
observable, recoverable, browser-qualified, and rollback-qualified.

## 3. Prerequisite matrix

| P0 | Environment | Credentials/access | External infrastructure | Repository workflow/tool | Witness/approval | Execution location | Dependencies | Effort |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Qualified promotion/staging | Real isolated staging Kubernetes environment plus production Kubernetes environment for final promotion | GitHub tag/workflow rights; GHCR pull and verification; protected-environment approver; staging and production cluster deploy access; staging and production External Secret read paths; DNS/TLS administration | Approved staging/production clusters, ingress/DNS/TLS, External Secrets operator and SecretStore, PostgreSQL, Neo4j, Keycloak, administratively separate recovery mount, telemetry access | `.github/workflows/runtime-image-release.yml`; `tools/ci/release_qualification.py`; `kubectl kustomize infra/environments/staging`; resolved release bundles; ADR-041 Jobs | Release Manager; Security reviewer for signature/provenance; staging operator; database operator; protected production approver | GitHub, staging, then production | Operational decisions; prior distinct qualified set; staging E2E; staging rollback; alerting/recovery readiness before final production approval | LARGE |
| Production alerting activation | Production monitoring plane with network reachability to production EMG metrics; staging may be used first for safe proof | Monitoring administration; Kubernetes namespace labeling/read access; dashboard/rule import; alert-routing configuration; receiving on-call endpoint | Approved Prometheus-compatible scraper/evaluator, cluster/datastore exporters where required, rule store, dashboard viewer, alert router/receiver | `observability/alerts/emg-platform-alerts.yaml`; `observability/dashboards/*.json`; `tests/infrastructure/test_alert_rules.py`; `tests/infrastructure/test_dashboards.py`; `tools/backup/emit_metrics.py`; alert runbook | Platform SRE operator; service owner; actual on-call recipient; Security witness for security alert route | Staging for dry activation; production for P0 closure | Monitoring decisions; deployed production metrics endpoints; production recovery metrics for backup/WAL alerts | LARGE |
| Target recovery/PITR witness | Production backup source and an isolated non-production restore environment in the target failure domain | Least-privilege backup DSN; remote repository read/write as separated roles; encryption/sign wrapper execution; escrowed decryption access; manifest verification; isolated restore-host administration; verifier DSN | Administratively separate durable POSIX repository, continuous WAL delivery, approved KMS/key wrapper and detached-signature custody, escrow copy in a separate domain, compatible isolated PostgreSQL restore host, capacity and network isolation | `tools/backup/scheduled-backup.sh`; `archive-wal.sh`; `verify-backup.sh`; `restore-full.sh`; `restore-pitr.sh`; `verify-recovery.sh`; recovery runbook; reconciliation and smoke procedures | Incident Commander; Database Operator; Security/key custodian; Evidence Owner; Service Owner | Production source plus isolated target environment; not active production restore | Recovery provider/custody decisions; production backup scheduling; monitoring of backup/WAL age; deployed release schema; target access | LARGE |
| Authenticated live E2E | Production-like staging running the exact qualified release set behind its real same-origin ingress | Staging test-human identity; approved tenant/clearance fixtures; browser access; Keycloak client/admin operator for setup only; read-only access to sanitized Audit/projection evidence; no browser-held service credentials | Staging Studio, Studio BFF, Keycloak with RFC 8693 permission, Knowledge Graph, Audit, Audit Projector, PostgreSQL, Neo4j, DNS/TLS/ingress | Existing Studio/BFF/KG endpoints and runbooks; browser execution checklist in this plan; repository component/integration suites as supporting evidence only | Integration Test Lead; Security witness; Product Owner; Audit/Evidence Owner | Staging only; local execution cannot close this P0 | Published set and successful staging deployment; working identity/delegation; Audit and datastore readiness; monitoring available for failure diagnosis | MEDIUM |

## 4. P0-1 — Qualified promotion and staging

### Required environment and access

A real namespace-isolated staging cluster must provide approved DNS/TLS, ingress,
external egress, staging-only PostgreSQL, Neo4j, Keycloak, External Secrets, recovery
storage, and telemetry. The production environment must provide the equivalent
production-owned inputs. Production credentials must not be reused in staging.

Required access is: protected-tag creation, GitHub workflow inspection and artifact
download, approval of the `production-release` environment, GHCR pull/verification,
Cosign/GitHub attestation verification, Kubernetes server-side dry-run and deployment,
External Secret status inspection, and database/Keycloak provisioning observation.

**OPERATIONAL DECISION REQUIRED:** select and authorize the staging platform/context,
cluster owners, DNS/TLS owner, External SecretStore integration, evidence-retention
duration, and a distinct prior release that is eligible for rollback. No repository ADR
chooses these.

### Exact execution

1. Record the approved source commit and ensure it is merged and clean:

   ```sh
   git fetch origin
   git switch develop
   git pull --ff-only origin develop
   git status --short
   git rev-parse HEAD
   ```

2. Run repository preflight before requesting a tag:

   ```sh
   .venv/bin/python tools/ci/validate_production_provisioning.py
   kubectl kustomize infra/environments/staging >/tmp/emg-staging-source.yaml
   kubectl kustomize infra/environments/production >/tmp/emg-production-source.yaml
   .venv/bin/pytest tests/infrastructure/test_runtime_image_supply_chain.py -q
   git diff --check
   ```

3. After Release Manager approval, create and push one protected release tag. Replace
   `vX.Y.Z-rc.N` only with the approved release identity:

   ```sh
   git tag -s vX.Y.Z-rc.N APPROVED_COMMIT -m "EMG V1 qualified release candidate"
   git push origin vX.Y.Z-rc.N
   ```

   The tag triggers `.github/workflows/runtime-image-release.yml`. Do not invoke a
   local build as a publication substitute. The protected GitHub approver reviews the
   source/tag and authorizes the privileged publication/signing jobs.

4. Download the completed workflow evidence into a controlled working directory and
   independently verify that it contains `release-images.json`, `sboms/`, `scans/`,
   `staging-resolved.yaml`, `production-resolved.yaml`, and repository qualification
   evidence. Verify each registry digest, Cosign issuer/workflow identity, GitHub
   attestation, manifest checksum, SBOM checksum, and zero-result blocking scan.

5. Select the intended staging context explicitly and verify identity before applying:

   ```sh
   kubectl config use-context APPROVED_STAGING_CONTEXT
   kubectl cluster-info
   kubectl auth can-i --list -n emg-staging
   kubectl apply --server-side --dry-run=server -f staging-resolved.yaml
   ```

6. Apply environment-owned External Secrets/endpoints first. Wait for Secret sync and
   dependency readiness. Apply `staging-resolved.yaml` in ADR-041 order: stage 10
   database roles; both stage 20 migrations; stage 30 Keycloak projector clients;
   stage 50 consistency validation; stage 60 Audit; stage 70 Audit Projector; then
   Identity, Knowledge Graph, Studio BFF, Studio, backup scheduling, and telemetry.
   Every Job and rollout must complete before the next dependent stage.

7. Run repository qualification against the downloaded artifact:

   ```sh
   .venv/bin/python tools/ci/release_qualification.py repository-qualify \
     --manifest release-images.json \
     --bundle staging-resolved.yaml \
     --sbom-directory sboms \
     --environment staging \
     --output staging-repository-qualification.json
   ```

8. After P0-4 smoke and the rollback rehearsal pass, create machine-generated
   `WITNESSED-STAGING-EVIDENCE.json` through the protected execution system. It must
   bind the exact manifest hash and release identity, record all checks `PASS`, set
   `stagingDeployment`, `smokeTests`, and `rollbackRehearsal` to `PASS`, set result to
   `WITNESSED_STAGING_QUALIFIED`, and identify the protected workflow/tag/run. Never
   edit repository-generated `PENDING` evidence into a pass.

9. Validate the current and distinct prior complete release sets:

   ```sh
   .venv/bin/python tools/ci/release_qualification.py rollback-gate \
     --current CURRENT/release-images.json \
     --previous PREVIOUS/release-images.json
   ```

   Deploy the prior complete digest set to staging, verify health/readiness and smoke,
   then redeploy the current complete set and verify again. Migration fingerprints must
   match; otherwise schema rollback is forbidden and a separately qualified forward fix
   is required.

10. After all four P0 evidence packages are approved, run:

    ```sh
    .venv/bin/python tools/ci/release_qualification.py promotion-gate \
      --evidence WITNESSED-STAGING-EVIDENCE.json \
      --manifest release-images.json
    ```

    Obtain protected production approval and apply `production-resolved.yaml` in the
    same ADR-041 order. No image may be rebuilt, retagged, or substituted.

### Evidence and witnesses

Capture tag/commit, workflow run URL, approval record, manifest and bundle SHA-256,
every image digest, scan/SBOM/signature/provenance verification, context/namespace,
External Secret readiness without values, Jobs and rollout outcomes, timestamps,
smoke results, rollback release identity and outcomes, promotion-gate output, and
production readiness. Required witnesses: Release Manager, Security reviewer,
Staging Operator, Database Operator, Integration Test Lead, and protected Production
Approver.

## 5. P0-2 — Production alerting activation

### Required environment and access

P0 closure requires an actual production scraper, rule evaluator, alert router, and
receiver with network access to EMG `/metrics`, Audit Projector port 9464, cluster
signals, datastore signals, and backup/WAL metrics. Staging should be used first for
safe rule and delivery qualification.

**OPERATIONAL DECISION REQUIRED:** select the Prometheus-compatible evaluation
backend, scraper namespace/identity, dashboard service, required cluster/datastore
exporters, receiver technology, on-call rotation, severity routing, ownership, and
retention. A platform-wide vendor choice may require Architecture Board approval.
This plan does not select Prometheus hosting, Grafana hosting, PagerDuty, Slack,
Opsgenie, email, or any substitute.

### Exact execution

1. Validate repository artifacts before import:

   ```sh
   .venv/bin/pytest tests/infrastructure/test_alert_rules.py \
     tests/infrastructure/test_dashboards.py \
     tests/infrastructure/test_emit_metrics.py -q
   ```

2. Provision the approved evaluator/router outside this repository. Label the approved
   scraper namespace to satisfy the existing NetworkPolicy contract:

   ```sh
   kubectl label namespace APPROVED_SCRAPER_NAMESPACE \
     networking.emg.io/observability-access=true --overwrite
   ```

3. Configure discovery for each service metrics endpoint, Audit Projector metrics,
   cluster metrics, PostgreSQL/Neo4j exporters where approved, and recovery textfile
   metrics. Import `observability/alerts/emg-platform-alerts.yaml` and the JSON files
   under `observability/dashboards/` without altering thresholds during activation.

4. Prove target discovery and rule evaluation in staging, then production: all required
   targets are up, rule groups load without error, expected time series exist, and no
   tenant, entity, principal, query, or credential occurs in metric labels.

5. Trigger one approved safe synthetic alert in staging and witness evaluator → router
   → actual receiver delivery. A temporary test series or safely isolated staging
   readiness condition may be used only if approved by SRE; do not disrupt production.
   Confirm the matching `docs/operations/alert-runbook.md` link and acknowledgement.

6. In production, witness at minimum rule evaluation, routing health, receiver reachability,
   and an approved non-destructive test notification through the real on-call route.
   Confirm backup/WAL freshness metrics after P0-3 scheduling is active.

### Evidence and witnesses

Capture evaluator identity/version, target inventory, last-scrape and rule-load status,
rule file checksum, dashboard import identity, sanitized metric samples, alert name and
timestamps, router event ID, receiver receipt/acknowledgement, runbook used, recovery
timestamp, and operator/reviewer identities. Required witnesses: Platform SRE,
Service Owner, receiving On-call Operator, and Security reviewer for the security route.

## 6. P0-3 — Target-environment recovery/PITR witness

### Required environment and access

Use the production PostgreSQL source and its administratively separate backup/WAL
repository, but restore only into a new isolated non-production target. The restore
host must match the recorded PostgreSQL major version and required locale, extensions,
libraries, permissions, storage capacity, and durability contract. Application egress
and normal credentials remain disabled until evidence review.

Required secret-managed capabilities are a least-privilege backup DSN, encryption and
decryption wrapper execution, manifest sign/verify wrapper execution, non-secret key
reference, escrow access, repository read/write separation, isolated restore admin,
and verifier DSN. Secret values must never appear in commands, logs, or evidence.

**OPERATIONAL DECISION REQUIRED:** select the administratively separate POSIX backup
repository/provider, failure domain, KMS/encryption and manifest-signature wrappers,
escrow owner/location, production PVC/mount implementation, restore host, repository
capacity/lifecycle controls, retention/evidence duration, and rehearsal window. Do not
use the scheduled PVC alone as proof of remote administrative separation.

### Exact execution

1. Configure PostgreSQL from `infra/backup/postgresql.conf.example`, mount the approved
   repository at the CronJob contract, synchronize `emg-postgresql-backup-secrets`, and
   configure continuous WAL archiving with `tools/backup/archive-wal.sh "%p" "%f"`.
   Confirm the daily 01:00 UTC CronJob and observe a successful scheduled run.

2. Independently verify the replicated backup in the separate failure domain:

   ```sh
   tools/backup/verify-backup.sh APPROVED_BACKUP/manifest.json
   ```

3. Record an authorized UTC recovery target that requires WAL replay. Provision a new
   empty isolated directory and export secret references through the approved runtime,
   then execute:

   ```sh
   export EMG_RECOVERY_MODE=isolated-restore
   export EMG_RECOVERY_CONFIRMATION=RESTORE_INTO_EMPTY_TARGET
   export EMG_RECOVERY_TARGET_ID=APPROVED_NONPRODUCTION_TARGET_ID
   tools/backup/restore-pitr.sh APPROVED_BACKUP EMPTY_TARGET \
     YYYY-MM-DDTHH:MM:SSZ promote
   ```

4. Start the restored PostgreSQL instance under recovery supervision. After it reaches
   the authorized target, supply the secret-managed verifier connection and run:

   ```sh
   tools/backup/verify-recovery.sh APPROVED_BACKUP/manifest.json
   ```

5. Validate migration checksums/history, approved row assertions, audit and custody
   chains/anchors, authoritative graph/revision state, outbox and dispatch counts,
   search-representation retention/cardinality, and representative authorized search.
   Keep Neo4j isolated, discard stale projection state, execute the existing deterministic
   PostgreSQL-to-Neo4j reconciliation path, and verify projected revision/hash before
   graph reads. Restart the qualified services in ADR-041 order and verify pending work,
   search, Audit, and projection behavior.

6. Measure RPO from the last recoverable transaction and RTO from incident/rehearsal
   start to verified recovery. Pass requires RPO no more than five minutes, RTO no more
   than four hours, intact ledgers, successful consistency gates, and multi-role review.
   Keep failed targets isolated; never silently choose another recovery point.

### Evidence and witnesses

Capture backup ID, signed manifest/hash, source/target failure-domain identifiers,
PostgreSQL version/timeline, recovery target, WAL range, byte volume, start/end times,
measured RPO/RTO, verification output, ledger anchors, migration result, outbox/dispatch
counts, search checks, Neo4j rebuild/revision evidence, service restart results, key
reference only, and destruction/retention disposition. Required witnesses: Incident
Commander, Database Operator, Security/Key Custodian, Evidence Owner, and Service Owner.

## 7. P0-4 — Authenticated live E2E qualification

### Required environment and access

Use the exact immutable release deployed to production-like staging behind real TLS and
same-origin ingress. Required infrastructure is Studio, Studio BFF, Keycloak with the
approved Authorization Code + PKCE and RFC 8693 permissions, Knowledge Graph, Audit,
Audit Projector, PostgreSQL, and Neo4j.

Use a dedicated staging human test identity with approved tenant, role, and clearance,
plus controlled fixtures at permitted and denied classifications. Operators need
sanitized read-only Audit, dispatch, PostgreSQL revision/outbox, and Neo4j projection
evidence access. The browser receives no bearer, refresh, service, or delegated token.

No repository browser E2E harness exists. Browser execution is therefore a witnessed
operational checklist using the deployed product; component tests are supporting, not
closure, evidence. Creating a new harness is outside this activation plan.

### Exact execution

1. Bind the session to the exact release manifest, staging context, namespace, ingress
   URL, and test fixture identifiers. Start browser network/console capture with headers,
   cookies, tokens, and query bodies redacted.
2. Open Studio and complete Keycloak authentication. Verify an opaque secure HttpOnly
   session, CSRF cookie/headers, no browser token storage, and same-origin `/bff/*` only.
3. Execute governed search by POST. Verify the raw query never enters URL/history,
   results contain no totals/hidden counts, permitted matches appear, denied
   classification does not leak, and Audit records Human Principal, Acting Service,
   and correlation continuity.
4. Open an entity, load the Explorer, and deliberately expand neighbors. Verify every
   rendered node/edge is authorized, expansion is bounded, and no hidden-count or
   completeness signal is exposed.
5. Switch English → Arabic → English and verify direction/content without changing
   authorization or issuing direct backend calls.
6. Execute one approved mutation. Verify authorization, authoritative PostgreSQL
   revision, mutation ledger/outbox, projector processing, Neo4j revision/hash, Audit
   append, Audit Projector delivery, and correlation continuity.
7. Exercise safe failure cases: missing/invalid CSRF, expired session, insufficient
   authorization, classification denial, token-exchange failure in a controlled test
   identity, cursor tampering, oversized search, bounded upstream timeout, controlled
   Audit unavailability, and controlled Neo4j stale/unavailable state. Verify fail-closed
   behavior and no sensitive error disclosure. PostgreSQL outage testing requires a
   separately approved staging failure window.
8. Log out, refresh, and verify the session remains logged out. Confirm cookies/session
   are invalidated and no direct Keycloak token endpoint or backend service URL was
   called by the browser.

### Evidence and witnesses

Capture manifest/bundle hashes, environment identity, timestamps, browser/version,
sanitized navigation and network-host inventory, session/cookie attribute assertions,
every scenario result, correlation IDs, sanitized Audit attribution, revision/outbox/
dispatch/projection identifiers, failure diagnostics, logout proof, and explicit
confirmation that raw queries/tokens were not retained. Required witnesses: Integration
Test Lead, Principal Security reviewer, Technical Product Owner, and Audit/Evidence Owner.

## 8. External-access blockers

1. Protected Git tag and `production-release` GitHub approval.
2. GHCR read/verification and workflow-artifact access.
3. Staging and production Kubernetes deploy contexts.
4. DNS/TLS, ingress, egress, External Secrets, and environment secret paths.
5. Staging and production PostgreSQL, Neo4j, and Keycloak administration.
6. Monitoring administration and actual on-call receiver access.
7. Production backup repository, KMS/signature wrapper, escrow, and isolated restore host.
8. Sanitized evidence access and availability of named human witnesses.

## 9. Operational decisions still blocking execution

Each item below is **OPERATIONAL DECISION REQUIRED** before its dependent step:

1. Staging platform, context, owners, DNS/TLS, ingress, egress, and SecretStore.
2. Monitoring evaluator/backend, scraper namespace, exporters, dashboard host, alert
   router/receiver, on-call ownership, and telemetry retention.
3. Backup repository/provider and failure domain, KMS/encryption/signature wrappers,
   escrow custody, mount implementation, restore host, capacity/lifecycle, and evidence
   retention.
4. Approved source/tag identity, distinct rollback release, activation window, witness
   roster, evidence custodian, and production approval authority.

Provider selection that establishes a platform-wide standard must be escalated to the
Architecture Board; a decision must not be inferred from examples in repository files.

## 10. Closure ledger

| Gate | Closure evidence | Status before execution |
| --- | --- | --- |
| Qualified promotion/staging | Exact published set; verified signatures/provenance/SBOM/scans; witnessed staging deploy/smoke/rollback; passing promotion gate; protected production deploy | OPEN |
| Production alerting | Production targets/rules healthy and real receiver delivery witnessed/acknowledged | OPEN |
| Target recovery/PITR | Remote-custody backup and WAL used for isolated target PITR; integrity/reconciliation pass; RPO/RTO achieved; multi-role approval | OPEN |
| Authenticated live E2E | Exact staging set passes authenticated browser, search, Explorer, mutation, Audit, projection, failure, and logout checklist | OPEN |

Overall activation is **NO-GO** until all four rows have immutable evidence and their
required witnesses approve it. A numerical readiness score cannot override this ledger.

## 11. First executable action

The first action that can be taken immediately without credentials or provider
assumptions is to convene the Architecture Board/SRE/Release/Database/Security owners
and record decisions for the four items in section 9, together with named operators and
witnesses. The first repository-grounded technical preflight, executable in parallel,
is:

```sh
git fetch origin
test "$(git rev-parse origin/develop)" = "9e3a1839a4e2aa109af1e4229f14f7da9603041c"
.venv/bin/python tools/ci/validate_production_provisioning.py
kubectl kustomize infra/environments/staging >/tmp/emg-staging-source.yaml
kubectl kustomize infra/environments/production >/tmp/emg-production-source.yaml
.venv/bin/pytest tests/infrastructure/test_runtime_image_supply_chain.py \
  tests/infrastructure/test_alert_rules.py \
  tests/infrastructure/test_dashboards.py \
  tests/infrastructure/test_backup_recovery.py -q
git diff --check
```

This preflight confirms repository readiness but closes no operational P0. The first
P0-reducing external action after decisions is approval and push of the protected
release tag for the agreed source commit.
