# observability/dashboards

RC-C (EMG v1 RC closure package): Grafana dashboard JSON, one per required
priority area (see `../README.md` for full context, the SLI inventory, and
the architectural-stop note on why no Grafana instance is deployed here).

| File | Covers |
|---|---|
| `emg-platform-health.json` | Service readiness, HTTP error rate/latency, dependency health |
| `emg-security-auth.json` | Authentication failures, mutation authorization denials |
| `emg-mutation-audit-pipelines.json` | KG mutation throughput/latency, Audit Projector dispatch backlog/delivery |
| `emg-datastore-projection-health.json` | Application-observed PostgreSQL/Neo4j reachability (deeper datastore-internal panels are bucket B/C — see file) |
| `emg-search-health.json` | Governed-search retained-representation count/storage |
| `emg-recovery-readiness.json` | Backup age / WAL archive lag / last verify status against the governed RPO/RTO |

Import into any Prometheus-compatible Grafana instance once one exists;
each dashboard's `templating.list` expects a Prometheus datasource variable
(update after import if the datasource UID differs). Validated by
`tests/infrastructure/test_dashboards.py`.

**This is not a backend decision.** These files are portable reference
artifacts (plain Grafana dashboard JSON, importable into self-hosted
Grafana, Grafana Cloud, Amazon Managed Grafana, or any other Grafana-
compatible viewer) authored so dashboard content is reviewed and ready now,
not evidence that Grafana has been selected as EMG's production monitoring
backend. That selection — and where/how any dashboard viewer is actually
deployed — remains an open architecture/operational decision; see
`../README.md`'s "Architectural stop" section.
