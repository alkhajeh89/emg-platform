# EMG platform alert runbook

Operator reference for every alert defined in
`observability/alerts/emg-platform-alerts.yaml` (RC-C, EMG v1 RC closure
package, closing RC-P0-C "Production alerting absent"). Each section below
is the `annotations.runbook` target of the matching alert and follows the
same structure: **meaning**, **likely causes**, **immediate checks**,
**escalation**, **recovery/mitigation**.

This document assumes an alert has already fired — it is not an
observability architecture explainer. For that, see
`observability/README.md` (implementation status, SLI inventory, SLO
approval table) and `docs/architecture/EMG_ADR-015_Unified_Enterprise_Observability.md`
(the governing ADR).

Every check below that reads application logs assumes the structured JSON
event schema `emg_telemetry.logger` already emits (`actor`, `module`,
`action`, `outcome`, `correlation_id`) — filter by `module` and `outcome` at
minimum.

---

## EMGServiceNotReady

**Meaning:** the named service's `/readyz` has reported degraded/unavailable
continuously for 2+ minutes. Kubernetes has almost certainly already pulled
the pod from Service endpoints (`readinessProbe periodSeconds: 5,
failureThreshold: 2` in `infra/kubernetes/base/*.yaml`), so this is real
capacity loss for that service, not an early warning.

**Likely causes:** a hard dependency the service's own readiness check
covers (see `EMGDependencyUnhealthy` below) is down; the process is
starting up slowly (check `startupProbe` did not itself fail); a bad
deployment; resource exhaustion (OOMKilled, CPU-starved).

**Immediate checks:**
1. `kubectl get pods -n emg-production -l app.kubernetes.io/name=emg-<service>` — pod phase, restart count, events.
2. `kubectl logs -n emg-production <pod> --previous` if recently restarted.
3. Query `emg_dependency_healthy{service="<service>"}` for the same window — is a specific dependency the cause?
4. `kubectl describe pod` for OOMKilled/scheduling/image-pull events.

**Escalation:** page on-call immediately (P0) if the service has zero ready
replicas (full outage, given every EMG workload runs `replicas: 1` today —
see RC review P1 item 3). If at least one dependency is the root cause,
also escalate per that dependency's own alert below.

**Recovery/mitigation:** restart the pod (`kubectl rollout restart
deployment/emg-<service>`) if a bad deploy or stuck process is suspected;
resolve the underlying dependency outage first if `EMGDependencyUnhealthy`
is also firing — restarting will not fix a downstream outage. Roll back to
the last known-good image digest per `docs/devops/RELEASE_MANAGEMENT.md` if
a recent deploy is implicated.

## EMGServiceMetricsAbsent

**Meaning:** no `emg_service_ready` series has been observed at all for the
named service for 5+ minutes — distinct from `EMGServiceNotReady`
(metric present but 0). Absence means either the service isn't running, or
its `/metrics` scrape target is unreachable (see network-policy note below)
— the monitoring pipeline itself may be the problem, not the service.

**Likely causes:** the service crashed before completing a single readiness
check; the metrics scrape target's NetworkPolicy allowance
(`emg-observability-scrape-http`/`-audit-projector` in
`infra/kubernetes/base/network-policies.yaml`) was never granted to the
scraper's namespace (`networking.emg.io/observability-access: "true"` —
this is an operational step outside this repository, see
`observability/alerts/emg-platform-alerts.yaml`'s ARCHITECTURAL STOP
comment); the scrape target configuration itself was never created.

**Immediate checks:**
1. `kubectl get pods -n emg-production -l app.kubernetes.io/name=emg-<service>` — does the pod exist and run at all?
2. From a pod in the scraper's namespace: `curl http://emg-<service>.emg-production.svc:8000/metrics` — does it return data?
3. `kubectl get networkpolicy -n emg-production emg-observability-scrape-http -o yaml` — confirm the namespaceSelector label the scraper's namespace needs.
4. Confirm the scrape target/service-discovery config on the monitoring side actually includes this service (bucket A/B boundary — this repository does not configure the scraper itself).

**Escalation:** P0. Treat as equivalent to a confirmed outage until proven
otherwise — do not assume "no data" means "fine."

**Recovery/mitigation:** if the pod is genuinely down, follow
`EMGServiceNotReady`'s recovery steps. If the pod is up but unscraped, this
is a monitoring-pipeline defect: apply the missing namespace label or fix
scrape-target configuration; this alert firing does not by itself indicate
a product outage, but must be resolved quickly because it also blinds every
other alert on this service.

## EMGDependencyUnhealthy

**Meaning:** the named service's own readiness check found one specific
upstream dependency (`postgres`/`neo4j`/`keycloak`/`audit_service`/
`knowledge_graph`) unhealthy for 3+ minutes, without necessarily failing
the whole service's readiness (e.g. Identity stays "ready" with
`audit_service` unhealthy — see `emg_identity.health.readiness`'s
degraded-not-unavailable design).

**Likely causes:** the dependency itself is down or unreachable (network
policy, DNS, credential rotation gone wrong); TLS/certificate expiry;
dependency-side resource exhaustion.

**Immediate checks:**
1. Identify the dependency from the `dependency` label; check that system's own health directly (e.g. Keycloak admin console, `psql` connectivity from a debug pod).
2. Check for a recent credential/secret rotation (`ExternalSecret` sync status) coinciding with the alert start time.
3. Check NetworkPolicy egress rules (`emg-internal-egress` et al. in `infra/kubernetes/base/network-policies.yaml`) haven't regressed.

**Escalation:** P1; escalate to P0 handling if the dependent service's own
`EMGServiceNotReady` also fires (i.e. the dependency is mandatory, not
degraded-tolerant).

**Recovery/mitigation:** restore the dependency; no action needed on the
EMG service itself once the dependency recovers (readiness checks
self-heal on the next probe).

## EMGHighServerErrorRate

**Meaning:** over 5% of the named service's requests in the last 5 minutes
returned an HTTP 5xx.

**Likely causes:** a bad deploy; a downstream dependency outage manifesting
as unhandled exceptions rather than a clean `EMGError` mapping; database
connection pool exhaustion; an unvalidated edge case in a recent code
change.

**Immediate checks:**
1. Cross-check `EMGDependencyUnhealthy`/`EMGServiceNotReady` for the same service/window.
2. Sample recent structured logs filtered to `outcome=error` for this service's `module` — look for a clustered `error_code`/exception type.
3. Check `http_errors_total` broken down by `error_code` (bucket A metric, same registry) to see whether one specific error code is spiking.

**Escalation:** P1; escalate to P0 if the rate is climbing toward 100% or
correlates with `EMGServiceNotReady`.

**Recovery/mitigation:** roll back a recent deploy if correlated in time;
otherwise treat as a code/dependency defect requiring investigation before
a fix can be shipped — this alert is a detection mechanism, not a
self-healing one.

## EMGHighAuthenticationFailureRate

**Meaning:** the named service is sustaining more than 1 `AUTHORIZATION_ERROR`
(EMG's shared 401 code) per second for 5+ minutes.

**Likely causes:** a client/credential rollout shipped an expired or
misconfigured secret; a Keycloak realm/client configuration change; a
credential-stuffing or token-replay attempt against a public endpoint.

**Immediate checks:**
1. Determine whether failures are concentrated on one client/service identity or spread broadly (structured logs carry `actor`; do not attempt to correlate by tenant/entity in metrics — see the alert file's cardinality-safety design).
2. Check for a recent Keycloak client-secret rotation that a caller wasn't updated for.
3. If spread broadly and not explained by a known rollout, treat as a potential credential-stuffing/replay attempt and involve security response.

**Escalation:** P1 by default; escalate immediately to security
incident response if a broad, unexplained spike suggests an attack rather
than a misconfiguration.

**Recovery/mitigation:** fix the misconfigured client/secret, or block the
offending source at the network/WAF layer if this is an attack (outside
this repository's scope — environment-owned).

## EMGElevatedRequestLatency

**Meaning:** p95 request latency for the named service has exceeded 5
seconds for 10+ minutes. Informational (P2) — a quality-trend signal, not a
tuned SLO breach; see `observability/README.md`'s SLO approval table.

**Likely causes:** database contention (see `EMGMutationLatencyElevated`
for the mutation-specific version); connection pool saturation; upstream
dependency slowness.

**Immediate checks:** review `http_request_duration_seconds` broken down by
`route`; check PostgreSQL/Neo4j load if available (bucket B — see
`emg-datastore` group).

**Escalation:** governance/engineering review, not paging, unless it
coincides with a P0/P1 alert.

**Recovery/mitigation:** capacity/query investigation; not an incident by
itself.

## EMGAuditDispatchBacklogGrowing

**Meaning:** the Audit Projector's largest single-tenant pending-dispatch
depth has exceeded 100 for 10+ minutes.

**Likely causes:** the Audit service is slow/degraded (check its own
`EMGHighServerErrorRate`/`EMGElevatedRequestLatency`); Keycloak token
exchange for the projector's service credentials is failing; mutation
volume has spiked beyond the projector's single-replica throughput.

**Immediate checks:**
1. `kubectl logs -n emg-production -l app.kubernetes.io/name=emg-audit-projector` — filter structured logs for `action=dispatch_delivery`, `outcome!=success`.
2. Check the Audit service's own health/error-rate alerts.
3. Confirm the projector pod itself is running (`EMGServiceNotReady`-equivalent for a headless worker is `kubectl get pods`, since it has no `/readyz` HTTP route — only the file-sentinel probe).

**Escalation:** P1; escalate to P0 handling if `EMGAuditDispatchOldestPendingTooOld` also fires.

**Recovery/mitigation:** resolve the underlying Audit service or Keycloak
issue; the projector's own retry/backoff (ADR-028 D-48) will drain the
backlog automatically once the blocker clears — no manual replay needed
unless entries have also become `EMGAuditDispatchExhaustedEntries`.

## EMGAuditDispatchOldestPendingTooOld

**Meaning:** the oldest not-yet-delivered audit dispatch entry (any tenant)
has been pending for over 15 minutes.

**Likely causes:** same as `EMGAuditDispatchBacklogGrowing`, but this is the
sharper, time-bound signal: a specific governed action has gone this long
without a durable audit record landing.

**Immediate checks:** same as `EMGAuditDispatchBacklogGrowing`, plus:
confirm the projector worker thread is alive (`kubectl exec` into the pod
and check `/tmp/emg-audit-projector-ready` exists and is recent, matching
`ProjectorRuntime._ready_path`).

**Escalation:** P0 — page on-call immediately. This is the RC-C adversarial
review's specific concern about audit failures being observable only
through the failed system itself; treat any sustained firing as a
compliance-relevant gap until the backlog is confirmed draining.

**Recovery/mitigation:** restart the projector pod if the worker thread has
silently died (`kubectl rollout restart deployment/emg-audit-projector`);
otherwise resolve the downstream Audit/Keycloak dependency. Once resolved,
confirm via `audit_dispatch_pending_depth_max` trending back toward 0.

## EMGAuditDispatchExhaustedEntries

**Meaning:** one or more audit dispatch entries have exhausted all 8
delivery attempts (ADR-028 D-48) and will not be retried automatically.

**Likely causes:** a sustained, multi-minute outage of the Audit service or
credential exchange that outlasted the retry/backoff window (max ~5
minutes of backoff across 8 attempts); a permanent delivery error (e.g. a
malformed event that the Audit service consistently rejects with 4xx).

**Immediate checks:**
1. Identify the exhausted mutation IDs from structured logs (`action=dispatch_delivery`, `outcome=exhausted`).
2. Determine whether the failure was `PermanentDeliveryError` (config/data problem, will not resolve by retrying) or repeated `RetryableDeliveryError` exhaustion (transient outage that ran too long).

**Escalation:** P0, no tolerance window — any value above 0 requires
investigation, since audit is the authoritative evidence trail (Module 6).

**Recovery/mitigation:** for a transient-outage exhaustion, a manual replay
mechanism is required — none exists in the repository as an automated
tool today; this is a known gap (see the final RC-C report's "Missing
telemetry"/"Architectural blockers" sections). For a permanent/malformed
event, escalate to engineering for a data-correction path; do not attempt
to silently resubmit a malformed event.

## EMGAuditDeliveryFailureRateElevated

**Meaning:** over 10% of audit dispatch delivery attempts (any outcome
other than `success`) over the last 10 minutes.

**Likely causes/immediate checks/escalation/recovery:** as
`EMGAuditDispatchBacklogGrowing` — this is the rate-based leading indicator
for the same underlying problem, usually firing before the depth/age
thresholds are crossed.

## EMGAuditProjectorMetricsAbsent

**Meaning:** no `audit_dispatch_delivery_total` observed in 10 minutes — an
ambiguous "no data" state that could mean a genuinely idle tenant or a dead
scrape target. The rule deliberately does not reference Prometheus's `up`
metric or any specific scrape-job name to avoid coupling this alert to a
deployment-specific scrape-config naming convention (bucket B); cross-check
whatever target-health view the eventual monitoring backend provides as a
separate step (see below), rather than expecting this rule to distinguish
the two cases itself.

**Likely causes:** a genuinely idle tenant (no mutations to dispatch, no
delivery events to record — plausible but should be rare in a
production tenant); a scrape-pipeline failure specific to the
audit-projector's separate metrics port (9464, not the main app port —
see `emg-audit-projector-metrics` Service and
`emg-observability-scrape-audit-projector` NetworkPolicy).

**Immediate checks:** as `EMGServiceMetricsAbsent`, adapted for the
audit-projector's dedicated metrics port/Service rather than the shared
`/metrics`-on-8000 pattern the four FastAPI services use.

**Escalation:** P1 (lower confidence than the P0 backlog/age alerts by
design — see the alert file's own comment on why this is intentionally
separated from `EMGAuditDispatchOldestPendingTooOld`).

**Recovery/mitigation:** as `EMGServiceMetricsAbsent`.

## EMGMutationFailureRateElevated

**Meaning:** over 5% of a given Knowledge Graph mutation operation
(`create_entity`/`replace_entity`/`replace_relationship`/
`close_relationship`/`merge_entities`) are failing with a 5xx (not merely
being rejected with a 4xx, which is normal client-side traffic).

**Likely causes:** PostgreSQL authoritative-write contention/failure;
Neo4j projection failure surfacing synchronously; a regression in mutation
validation/atomic-execution logic.

**Immediate checks:**
1. Cross-check `EMGDependencyUnhealthy{service="knowledge-graph"}`.
2. Sample structured logs for `module=knowledge_graph.mutations`, `outcome=failure`.
3. Check `kg_mutation_latency_seconds` for the same operation — is this a timeout-driven failure?

**Escalation:** P1; escalate to P0 if correlated with
`EMGDependencyUnhealthy{dependency="postgres"}` (authoritative-store
failure).

**Recovery/mitigation:** resolve the underlying datastore issue; roll back
a recent mutation-path deploy if correlated in time.

## EMGMutationAuthorizationDenialsSpike

**Meaning:** Knowledge Graph mutation authorization (PolicyEngine) denials
exceed 1/sec for 5+ minutes.

**Likely causes:** a policy/role configuration rollout that unintentionally
denies a legitimate client; a probing/enumeration attempt against write
endpoints.

**Immediate checks:** confirm whether a policy config change
(`services/knowledge-graph/config/policy.example.yaml` equivalent in
production) shipped recently; check whether denials are concentrated on
one operation or spread broadly.

**Escalation:** P1; escalate to security response if broad/unexplained
(write-endpoint probing is higher-value to an attacker than read-endpoint
probing).

**Recovery/mitigation:** revert the policy change if it's the cause;
involve security response if this looks adversarial.

## EMGMutationLatencyElevated

**Meaning:** p95 mutation latency for a given operation exceeds 10s for
10+ minutes. Informational (P2).

**Likely causes/checks:** as `EMGElevatedRequestLatency`, scoped to the
mutation path specifically (PostgreSQL write + optional Neo4j read-repair).

**Escalation/recovery:** governance review; capacity/query investigation.

## EMGSearchRetentionMetricsAbsent

**Meaning:** no `kg_search_representations_total` observed for 30+
minutes, while the knowledge-graph service is otherwise up.

**Likely causes:** the search-metrics collector itself failing (check for
exceptions around `emg_knowledge_graph_api.search_metrics.install_search_metrics_collector`'s
throttled collector callback — it swallows exceptions by the
`MetricsRegistry.render()` contract, so check application logs, not just
alert state); `store_backend` is not `postgres` in this environment (the
collector is intentionally a no-op there).

**Immediate checks:** confirm `emg_service_ready{service="knowledge-graph"}`
is healthy first (rules out a full outage); check `store_backend`
configuration.

**Escalation:** P2 — informational, this does not indicate search itself is
broken, only that its storage/retention telemetry is unavailable.

**Recovery/mitigation:** investigate the collector; if `store_backend` is
intentionally not `postgres`, this alert firing is expected and should be
suppressed for that environment (an Alertmanager routing/silence concern —
bucket B, outside this repository).

## EMGPodCrashLooping

**Status:** bucket B/C — requires kube-state-metrics to be deployed
in-cluster; not present in this repository (see the `emg-cluster-workload`
group's docstring in `observability/alerts/emg-platform-alerts.yaml`). Rule
logic is reviewed and ready; operator action needed before it can fire.

**Meaning (once live):** a pod has restarted more than 3 times in 15
minutes.

**Likely causes:** an unhandled startup exception; a bad config/secret
shipped with the last deploy; OOMKill under sustained load; a liveness
probe misconfiguration causing the kubelet to kill a healthy-but-slow
process.

**Immediate checks:** `kubectl get pods -n emg-production`; `kubectl
describe pod` for the last-terminated-state reason (OOMKilled vs Error);
`kubectl logs --previous`.

**Escalation:** P0 — every EMG workload runs `replicas: 1` today (RC review
P1 item 3), so a crash loop is a full capability outage, not partial
degradation.

**Recovery/mitigation:** roll back the last deploy if correlated in time
(`docs/devops/RELEASE_MANAGEMENT.md`); fix the underlying startup defect;
raise resource limits if OOMKilled and the workload's memory profile has
legitimately grown.

## EMGDeploymentReplicasUnavailable

**Status:** bucket B/C — requires kube-state-metrics; see
`EMGPodCrashLooping` above for the same dependency note.

**Meaning (once live):** a Deployment has one or more replicas that are not
available (distinct from crash-looping — covers stuck rollouts,
scheduling failures, and readiness-probe failures that don't trigger
restarts).

**Immediate checks:** `kubectl rollout status deployment/emg-<service> -n
emg-production`; `kubectl describe deployment` for the rollout condition.

**Escalation:** P0, same reasoning as `EMGPodCrashLooping` (single-replica
topology).

**Recovery/mitigation:** `kubectl rollout undo` if a stuck rollout;
otherwise as `EMGServiceNotReady`.

## EMGContainerMemoryNearLimit

**Status:** bucket B/C — requires cAdvisor (via metrics-server/kubelet) and
kube-state-metrics for the limit series; not present in this repository.

**Meaning (once live):** a container's working-set memory is above 90% of
its declared `resources.limits.memory` (see the relevant
`infra/kubernetes/base/*.yaml`).

**Immediate checks:** `kubectl top pod -n emg-production`; check for a
recent traffic/data-volume increase; check for a memory leak signature
(steady climb with no plateau across multiple deploys).

**Escalation:** P1 — leading indicator of an imminent OOMKill
(`EMGPodCrashLooping`), not yet an outage.

**Recovery/mitigation:** raise the memory limit if the workload's
legitimate footprint has grown; investigate for a leak otherwise.

## EMGContainerCPUThrottlingHigh

**Status:** bucket B/C — requires cAdvisor; not present in this repository.

**Meaning (once live):** a container has been CPU-throttled (hit its CFS
quota) more than 25% of the time over 15+ minutes.

**Immediate checks:** `kubectl top pod`; compare request/limit CPU values
against observed usage patterns.

**Escalation:** P2 — quality/capacity trend, not an incident by itself.

**Recovery/mitigation:** raise the CPU limit or investigate/optimize the
workload for sustained throttling.

## EMGPostgresDown

**Status:** bucket B/C — requires `postgres_exporter` against the
environment-owned PostgreSQL instance (ADR-041); not deployed by this
repository. Until then, `EMGDependencyUnhealthy{dependency="postgres"}`
(bucket A, live today) is the closest available signal, though it only
reports reachability, not internal PostgreSQL state.

**Meaning (once live):** the exporter's own PostgreSQL scrape target is
down.

**Immediate checks (once live):** direct `psql` connectivity check from a
debug pod; PostgreSQL host/instance status via the environment's own
infrastructure tooling (outside this repository — ADR-041 environment-owned).

**Escalation:** P0 — PostgreSQL is authoritative for everything (Modules
6/7); this is a platform-wide outage.

**Recovery/mitigation:** environment/DBA-owned; outside this repository's
scope beyond alerting on it. Cross-check `docs/operations/postgresql-backup-recovery.md`
if recovery/restore is required.

## EMGPostgresReplicationLagHigh

**Status:** bucket B/C — requires `postgres_exporter`; see
`EMGPostgresDown` above.

**Meaning (once live):** replication lag on a read replica exceeds 30
seconds.

**Immediate checks (once live):** `pg_stat_replication` on the primary;
replica host resource utilization.

**Escalation:** P1 — degrades read-path freshness, not yet an outage
(PostgreSQL authoritative reads/writes are not replica-dependent per the
accepted persistence architecture).

**Recovery/mitigation:** environment/DBA-owned.

## EMGPostgresConnectionPoolNearSaturation

**Status:** bucket B/C — requires `postgres_exporter`; see
`EMGPostgresDown` above.

**Meaning (once live):** active connections exceed 90% of the PostgreSQL
instance's `max_connections`.

**Likely causes:** a connection-pool leak in one service; a burst in
traffic across multiple services sharing the instance; a service
misconfigured with too-large a `postgres_pool_max_size`.

**Immediate checks (once live):** `pg_stat_activity` grouped by
application/client; each service's own `postgres_pool_max_size`
configuration sum against `max_connections`.

**Escalation:** P1 — shared-fate risk across every service using that
PostgreSQL instance; escalate to P0 if connections are already refused.

**Recovery/mitigation:** identify and fix the leaking/over-provisioned
service; raise `max_connections` only after confirming it's not masking a
leak.

## EMGBackupAgeExceeded

**Meaning:** no successful PostgreSQL backup recorded in over 24 hours.
Threshold is `docs/operations/postgresql-backup-recovery.md`'s own
documented alerting requirement, not invented for this alert.

**Likely causes:** the daily backup schedule (`tools/backup/full-backup.sh`,
documented to run at 01:00 UTC) failed or was never actually scheduled in
production (RC-P0-D, a sibling P0 to this one, covers production backup
scheduling — see `docs/release/EMG_V1_RELEASE_CANDIDATE_CLOSURE_REVIEW.md`).

**Immediate checks:**
1. Confirm whether a production scheduler for `tools/backup/full-backup.sh` exists and ran (RC-P0-D dependency — it may not exist yet).
2. If it ran, check its exit code/logs and `tools/backup/emit_metrics.py backup-success` was actually invoked afterward.
3. Check available storage/credentials the backup script depends on (KMS key, target bucket/path).

**Escalation:** P0 — every hour without a valid backup extends potential
data loss exposure beyond the documented 5-minute RPO expectation for a
truly current recovery point.

**Recovery/mitigation:** run `tools/backup/full-backup.sh` manually if the
scheduler is broken; fix the scheduler; verify the resulting backup with
`tools/backup/verify-backup.sh`.

## EMGWalArchiveLagExceeded

**Meaning:** WAL archive age exceeds five minutes — the documented RPO
(`docs/operations/postgresql-backup-recovery.md`).

**Likely causes:** WAL archiving process stopped/errored;
`archive_timeout` misconfigured or PostgreSQL itself under distress;
storage target for archived WAL unreachable.

**Immediate checks:** PostgreSQL's own `pg_stat_archiver` view
(`last_archived_time`, `last_failed_time`); `tools/backup/archive-wal.sh`
logs/exit status.

**Escalation:** P0 — this is a direct RPO breach, not a leading indicator.

**Recovery/mitigation:** restart WAL archiving; investigate and resolve the
storage/permission/connectivity issue blocking archive completion.

## EMGBackupChecksumFailure

**Meaning:** the most recent backup failed checksum/manifest verification
(`tools/backup/verify-backup.sh` → `backup_manifest.py validate
--verify-files`).

**Likely causes:** storage corruption; an incomplete/interrupted backup
run; a manifest/artifact mismatch from a partial upload.

**Immediate checks:** re-run `tools/backup/verify-backup.sh` against the
same manifest to rule out a transient read error; inspect the manifest's
`artifacts[].sha256` against the actual stored objects.

**Escalation:** P0 — a backup that fails verification is not a usable
recovery point; this directly threatens the RTO objective if the prior
valid backup is also old.

**Recovery/mitigation:** trigger a fresh full backup immediately; do not
delete the failed backup until root-caused (evidence for the storage/
corruption investigation).

## EMGBackupMetricsAbsent

**Meaning:** no backup-freshness metric observed at all — as opposed to
`EMGBackupAgeExceeded` (metric present but stale). Kept as P1, not P0,
specifically because until RC-P0-D's production backup scheduler exists,
this alert is EXPECTED to fire continuously — see
`docs/release/EMG_V1_RELEASE_CANDIDATE_CLOSURE_REVIEW.md` RC-P0-D. It is a
known, tracked gap, not a fresh incident, and should not page on-call
repeatedly for a condition operators already know about; it exists so the
gap stays visible rather than silently disappearing from dashboards.

**Immediate checks:** confirm whether `tools/backup/emit_metrics.py` is
wired into the production backup/WAL-archive/verify cron path yet (RC-P0-D
dependency). If it is wired in and this still fires, investigate the
scrape/textfile-collector path (bucket B — node_exporter's
`--collector.textfile.directory` must point at
`emit_metrics.py`'s `--output`).

**Escalation:** P1, informational until RC-P0-D closes.

**Recovery/mitigation:** complete RC-P0-D (production backup scheduling);
this alert should stop firing once a scheduled job successfully calls
`emit_metrics.py` for the first time.
