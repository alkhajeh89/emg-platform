# /infra — Infrastructure as Code (ADR-017, Engineering Master Plan §5)

Kubernetes-based infrastructure across environment tiers, defined as code
and environment-promoted rather than hand-configured (Engineering Master
Plan §5). Capacity/scaling follows ADR-017's compounded-load model.

The production Kubernetes deployment foundation is implemented under
`kubernetes/base` and `environments/production` for RC-1A.  Local
`docker-compose.yml` remains development-only.  Cluster provisioning,
capacity/HA/DR, release engineering, and air-gapped packaging remain separate
work:

- FEAT-11-1 Kubernetes Cluster Provisioning
- FEAT-11-2 Infrastructure-as-Code Baseline
- FEAT-11-3 Secrets Management
- FEAT-11-4 Capacity & HA/DR Implementation
- FEAT-11-5 Air-Gapped Deployment Packaging

## Structure

```
environments/local/                  Local dev orchestration reference (see root docker-compose.yml)
environments/development/            Shared development/integration tier
environments/staging/                Staging tier
environments/production/             Production tier
environments/air-gapped-production/  Disconnected production variant (Module 9 §7)
modules/                             Reusable IaC modules (compute/network/storage) — TASK-11-1
kubernetes/                          Cluster manifests / Helm charts — FEAT-11-1
```

Ownership: CTO function (infrastructure), joint with each module's
Accountable Owner for capacity/scaling decisions (ADR-016 Section 8).
