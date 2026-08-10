# observability/alerts

RC-C (EMG v1 RC closure package, closing RC-P0-C "Production alerting
absent"): `emg-platform-alerts.yaml` is the alert rule set, in standard
Prometheus rule-group YAML. Read its own header comment first — it
contains the full ARCHITECTURAL STOP note on what is and is not decided
(evaluation engine, scrape access, alert routing) before assuming any of
these can page anyone today.

Ownership-driven alert routing (ADR-015 §10, via ADR-016's ownership
registry) is not implemented: ADR-016 itself has no accepted, populated
ownership registry to route from yet. `severity`/`category` labels are the
routing input a future Alertmanager config would consume.

Every P0/P1 (and P2) alert links to `docs/operations/alert-runbook.md` via
its `annotations.runbook` field. Validated by
`tests/infrastructure/test_alert_rules.py` (YAML syntax, required fields,
runbook-anchor resolution, privacy/cardinality safety, and — for alerts
claiming to be implementable now — that the metric they reference actually
exists in this repository's instrumentation).
