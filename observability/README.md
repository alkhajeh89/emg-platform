# /observability — Shared Dashboards & Alerting (ADR-015)

Shared observability definitions, owned centrally rather than duplicated
per service (Engineering Master Plan §3), implementing the Unified
Enterprise Observability model (ADR-015): correlated logs, metrics, and
traces across every module.

**Out of Sprint 1 scope.** Folder structure only. The client-side telemetry
primitives (structured logging + correlation-ID propagation) are scaffolded
this sprint in `/libs/python/emg-telemetry` (FEAT-01-2) and wired into
services starting Module 4 (EPIC-02), per Engineering Master Plan §11:
"Observability instrumentation ... is instrumented starting with Module 4,
not added retroactively." Dashboards, alert routing, and SLO/error-budget
tracking are EPIC-12 (Sprint 20+):

- FEAT-12-3 Observability Platform
- FEAT-12-4 Alerting & SLO/Error Budget

## Structure

```
dashboards/   Role-scoped dashboard definitions (ADR-015 §9) — engineering
              operations, knowledge/data stewardship, AI governance,
              decision-support views
alerts/       Alert routing rules, ownership-driven per ADR-016 (ADR-015 §10)
```

Ownership: CTO function / Platform SRE Team (ADR-016 Section 1, item 9).
