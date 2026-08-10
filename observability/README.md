# /observability — Shared Dashboards & Alerting (ADR-015)

Shared observability definitions, owned centrally rather than duplicated
per service (Engineering Master Plan §3), implementing the Unified
Enterprise Observability model (ADR-015): correlated logs, metrics, and
traces across every module.

**RC-C update (EMG v1 RC closure package, closing RC-P0-C "Production
alerting absent"):** metrics emission, alert rules, and dashboards now
exist — see the structure below. This closes the *content* gap RC-P0-C
identified. It does **not** close the *infrastructure* gap: no metrics
backend (Prometheus/Alertmanager/Grafana or equivalent) is deployed by this
repository, and none is selected by any ADR. See "Architectural stop" below
before assuming this package alone makes an alert page anyone.

## Structure

```
dashboards/   Grafana dashboard JSON (ADR-015 §9) — platform health,
              security/auth, mutation/audit pipelines, datastore/
              projection health, search health, recovery readiness
alerts/       emg-platform-alerts.yaml — Prometheus-format alerting rules
              (ADR-015 §10), routing INPUT (severity/category labels) only;
              ownership-driven routing per ADR-016 remains unimplemented
              (ADR-016 itself has no accepted ownership registry yet)
```

Ownership: CTO function / Platform SRE Team (ADR-016 Section 1, item 9).

## Architectural stop

`docs/infrastructure/OBSERVABILITY_INFRASTRUCTURE.md` and
`docs/backend/implementation/OBSERVABILITY_ARCHITECTURE.md` both say "TBD —
requires engineering or architecture decision," and no ADR selects a
metrics/alerting/dashboard backend. This package deliberately does not
invent one. What it does instead:

- Every service emits metrics in **Prometheus text-exposition format**
  (`emg_telemetry.metrics` — a small, dependency-free, hand-rolled
  registry; see that module's docstring for why no `prometheus_client`
  dependency was added). This format is the same one virtually every
  Prometheus-compatible backend can ingest, so choosing it does not lock in
  a specific vendor or hosting model.
- Alert logic is written in **Prometheus rule-group YAML**
  (`alerts/emg-platform-alerts.yaml`), the standard portable representation
  for that exposition format.
- Dashboards are **Grafana dashboard JSON** (`dashboards/*.json`), the
  standard viewer paired with Prometheus-compatible metrics, importable
  into self-hosted Grafana, Grafana Cloud, or a managed Grafana service.

None of this deploys or configures an actual running system. Three things
remain genuinely undecided and are called out explicitly (also repeated in
`alerts/emg-platform-alerts.yaml`'s own header comment):

| # | Decision | Who | Notes |
|---|---|---|---|
| A | Where alert rules are evaluated (self-hosted Prometheus/Thanos/Cortex/Mimir vs. a managed service) | Architecture Board + SRE | Some paths need a new ADR (platform-wide vendor choice); a scoped choice may only need operational sign-off |
| B | Who scrapes `/metrics` (which namespace runs the scraper) | SRE / Platform ops | `infra/kubernetes/base/network-policies.yaml`'s `emg-observability-scrape-http`/`-audit-projector` policies already grant access to any namespace labeled `networking.emg.io/observability-access: "true"` — applying that label is the only remaining step once a scraper exists |
| C | Where alerts route (PagerDuty/Slack/Opsgenie/email, on-call rotation) | SRE, per ADR-016's not-yet-accepted ownership registry | `severity`/`category` labels in the alert file are the routing *input*; no Alertmanager receiver config exists anywhere in this repository |

## What is implemented now (bucket A)

Metrics, wired into existing code with **no new production dependency**
(hash-locked `requirements-production.lock`/`.in` are unchanged):

| Signal | Metric(s) | Emitted by |
|---|---|---|
| Service readiness | `emg_service_ready{service}` | Every service's existing `/readyz` handler |
| Dependency health | `emg_dependency_healthy{service,dependency}` | Same `/readyz` handlers, per named dependency |
| HTTP request rate/latency/errors | `http_requests_total`, `http_request_duration_seconds`, `http_errors_total` | `emg_telemetry.http_metrics` middleware + existing `emg_error_handler` in every FastAPI service |
| Audit dispatch delivery/backlog | `audit_dispatch_delivery_total`, `audit_dispatch_delivery_duration_seconds`, `audit_dispatch_pending_depth_{sum,max}`, `audit_dispatch_oldest_pending_age_max_seconds`, `audit_dispatch_in_flight_sum`, `audit_dispatch_exhausted_sum` | `emg_audit_projector.telemetry.PrometheusProjectorObserver`, wired into the already-existing `ProjectorObserver` protocol |
| KG mutation requests/latency/denials | `kg_mutation_requests_total`, `kg_mutation_latency_seconds`, `kg_mutation_idempotency_hits_total`, `kg_mutation_authorization_denials_total` | `emg_knowledge_graph_api.mutation_observability` (already-existing structured-event module, now dual-emitting) |
| Governed-search retention/storage | `kg_search_representations_total`, `kg_search_total_bytes`, `kg_search_representation_max_node_count` | `emg_knowledge_graph_api.search_metrics`, wired to `GraphStore.search_representation_metrics()` |
| Backup/WAL-archive freshness | `emg_backup_last_success_timestamp_seconds`, `emg_wal_archive_last_success_timestamp_seconds`, `emg_backup_last_verify_status` | `tools/backup/emit_metrics.py` (standalone; not yet wired into a production cron path — see RC-P0-D) |

Every metric above is aggregate/service-scoped only — no tenant ID, entity
ID, principal ID, query content, or credential ever appears as a label or
metric name. See each module's docstring for the specific cardinality-bound
reasoning (`MAX_LABEL_VALUES_PER_METRIC`, tenant aggregation in
`PrometheusProjectorObserver`, route-template-not-resolved-path in
`http_metrics`).

## What requires additional infrastructure (bucket B/C — not implemented)

- **Cluster-level signal** (pod restarts/crash-loop, replica availability,
  container memory/CPU saturation): requires kube-state-metrics and
  cAdvisor/metrics-server in-cluster. Rule logic exists
  (`emg-cluster-workload` group) but is inert until deployed.
- **Datastore-internal signal** (PostgreSQL replication lag, connection-pool
  saturation, Neo4j internals): requires `postgres_exporter`/a Neo4j
  exporter against the environment-owned database instances (ADR-041).
  Deploying a third-party community image also touches ADR-040's governed
  image inventory. Rule logic exists (`emg-datastore` group) but is inert.
- **Backup/WAL-archive metric emission wired into production**: the emitter
  script exists and is unit-tested, but no CronJob/scheduler for
  `tools/backup/*.sh` exists anywhere in this repository — that is RC-P0-D,
  a sibling P0, not part of this package's scope.

## SLI inventory

Service Level Indicators measurable **today**, against the metrics above
(ADR-015 §11: "SLIs are defined per layer against the shared metric
taxonomy"):

| Layer | SLI | Metric basis |
|---|---|---|
| Platform (identity/audit/knowledge-graph/studio-bff) | Availability (readiness ratio) | `emg_service_ready` |
| Platform | HTTP error rate | `http_requests_total{status_class="5xx"} / http_requests_total` |
| Platform | HTTP request latency (p50/p95/p99) | `http_request_duration_seconds` histogram |
| Identity/Auth | Authentication failure rate | `http_errors_total{error_code="AUTHORIZATION_ERROR"}` |
| Audit (Module 6) | Dispatch delivery success rate | `audit_dispatch_delivery_total` by outcome |
| Audit | Dispatch latency (delivery duration) | `audit_dispatch_delivery_duration_seconds` |
| Audit | Backlog depth / age | `audit_dispatch_pending_depth_max`, `audit_dispatch_oldest_pending_age_max_seconds` |
| Knowledge Graph (Module 7) mutation | Mutation success/failure rate by operation | `kg_mutation_requests_total` by outcome |
| Knowledge Graph mutation | Mutation latency (p50/p95/p99) by operation | `kg_mutation_latency_seconds` histogram |
| Governed Search (Module 8, ADR-042) | Retained-representation count / storage | `kg_search_representations_total`, `kg_search_total_bytes` |
| Recovery | Backup freshness / WAL archive lag | `emg_backup_last_success_timestamp_seconds`, `emg_wal_archive_last_success_timestamp_seconds` |

Not measurable today (no SLI basis exists — new instrumentation or new
infrastructure required, see "bucket B/C" above and the Missing Telemetry
section of the RC-C final report):

- Knowledge Graph projection staleness/lag (checkpoint vs. revision head) —
  no application-level metric exists; `emg_persistence.projection`'s
  `ProjectionWorker` is not a continuously running production service today
  (it is an explicit operator/CI catch-up path — see its own module
  docstring), so there is nothing to instrument as a running backlog. A
  correct implementation would need new persistence-layer code exercised
  against live PostgreSQL/Neo4j, which this change does not add untested.
- PostgreSQL/Neo4j internal state (see bucket B/C above).
- AI Observability, Decision Observability (ADR-015 §4, §7) — not
  applicable; those modules are not implemented in EMG v1 (ADR-019/020/021
  remain proposed).
- Search-layer strategy health (lexical/semantic/graph/federated per-strategy
  breakdown, ADR-015 §6) — EMG v1's governed search is a single strategy;
  the multi-strategy breakdown ADR-015 describes does not yet apply.

## SLO recommendations vs. approved thresholds

ADR-015 §12 is explicit: **"Specific numeric SLO targets are an
implementation-phase, capacity-planning-dependent decision (see ADR-017)
and are not fixed by this ADR."** No load/capacity/stress test has been run
against this platform (RC review: "No approved platform SLO, production
load/stress test ... was found"). This package does **not** invent SLO
numbers. The table below separates two different kinds of number that
might look similar:

1. **Alert thresholds already in `emg-platform-alerts.yaml`** — these are
   either (a) grounded directly in an already-governed, documented value
   (backup age 24h / WAL lag 5min, sourced verbatim from
   `docs/operations/postgresql-backup-recovery.md`), or (b) a fixed safety
   trip-wire independent of workload (e.g. "90% of a resource *limit already
   declared in the Kubernetes manifest*" — not a capacity judgment, just
   proximity to a number the deployment already committed to). These are
   implemented and do not require further approval to exist as safety nets,
   though SRE should review the trip-wire values.
2. **SLO targets** — a committed reliability promise with an error budget
   attached (ADR-015 §12–13). None exist. The table below is what SRE/the
   Architecture Board would need to approve before any of these become real
   SLOs, not a recommendation to adopt these specific numbers:

| Candidate SLO | SLI basis | Status |
|---|---|---|
| Platform availability (e.g. 99.9% readiness ratio, 30-day window) | `emg_service_ready` | **Not approved** — no HA/capacity qualification exists; every workload is single-replica today (RC review P1 item 3), which itself may cap the achievable number regardless of target |
| HTTP p95 latency (e.g. < 1s) | `http_request_duration_seconds` | **Not approved** — no load test baseline |
| Audit dispatch delivery success rate (e.g. 99.99%) | `audit_dispatch_delivery_total` | **Not approved** — no historical baseline; audit is compliance-relevant, so this number in particular should not be picked without SRE + governance sign-off |
| KG mutation p95 latency (e.g. < 2s) | `kg_mutation_latency_seconds` | **Not approved** — no load test baseline |
| Backup RPO / RTO | `emg_backup_last_success_timestamp_seconds` etc. | **Already governed** (5 min / 4 hours, `docs/operations/postgresql-backup-recovery.md`) — this is the one row in this table that already has an approved target; it is encoded directly in the alert file, not listed here as a gap |

Error budgets (ADR-015 §13) cannot exist before the corresponding SLO is
approved; none are proposed here for the same reason.

## Testing

`tests/infrastructure/test_alert_rules.py` — YAML validity, required-field
linkage (severity/summary/description/runbook), balanced PromQL syntax,
privacy/cardinality-safety (no tenant/entity/query/credential terms),
bucket-A alerts reference only metrics this repository actually emits
(mechanically cross-checked against the instrumentation source), every
runbook anchor resolves to a real `docs/operations/alert-runbook.md`
heading and vice versa.

`tests/infrastructure/test_dashboards.py` — JSON validity, required Grafana
fields, UID/panel-ID uniqueness, panel targets reference only real metrics,
no tenant/entity/query/credential content, every panel has a `gridPos`.

`tests/infrastructure/test_emit_metrics.py` — the backup/WAL-archive metric
emitter's Prometheus-text-format output, atomicity, and independent-
invocation-preserves-other-metrics behavior.

`libs/python/emg-telemetry/tests/test_metrics.py` and `test_http_metrics.py`
— the metrics registry itself (exposition format, cardinality guard,
label-injection safety, concurrency) and the FastAPI integration
(route-template labeling, error counting, content type).

`services/audit-projector/tests/test_telemetry_metrics.py` and
`test_metrics_server.py` — the Prometheus projector observer (tenant
aggregation, never labels with tenant/mutation ID) and the standalone
metrics HTTP server.

None of these tests exercise a live Prometheus/Alertmanager/Grafana —
no such system is deployed anywhere this repository controls.
