# EMG™ — Enterprise Memory Graph Core Platform

Monorepo for the EMG™ Core Platform, implementing **Architecture Baseline v1.0**
(Product Vision through ADR-017, frozen) under the **Engineering Master Plan**
and **Engineering Backlog v1.0**.

## Status

| Phase | Status |
| --- | --- |
| Architecture Phase | Closed — Architecture Baseline v1.0 frozen |
| Engineering Phase | Active — Sprint 6 (EPIC-04 Audit Platform, complete — pending merge) |

**Sprint 1** (EPIC-01 Foundation — complete): repository bootstrap, monorepo
structure, local development environment, CI pipeline skeleton, branch
protection, CODEOWNERS, shared library scaffolding, documentation folders,
developer tooling, and infrastructure folders.

**Sprint 2** (EPIC-02 Identity, FEAT-02-1 + FEAT-02-2 — complete): the
`identity` service (Module 4) — Keycloak-backed authentication and EMG
session issuance/refresh. See `services/identity/README.md` and
`SPRINT-2-STATUS.md`.

**Sprint 3** (EPIC-02 Identity, FEAT-02-3 + FEAT-02-4 — complete): service
identity & OAuth 2.0 Client Credentials (M2M) authentication, and identity
federation readiness (LDAP/AD/external OIDC/SAML configuration + validation,
no external directory connected). See `services/identity/README.md`,
`docs/engineering/service-identity-registration.md`,
`docs/engineering/federation-readiness.md`,
`docs/engineering/security-limitations.md`, and `SPRINT-3-STATUS.md`.

**Sprint 4** (EPIC-03 Authorization Platform, FEAT-03-1 + FEAT-03-2 —
complete): a library-first Policy Enforcement Point and ABAC policy engine —
`libs/python/emg-auth-client`'s `PolicyEnforcementPoint` contract and
`Decision`/`AuthorizationRequest` types, and the new
`libs/python/emg-policy-engine` package (default-deny, fail-closed,
deny-overrides evaluation, supporting both human `Principal` and machine
`ServicePrincipal` callers). `services/identity` wires the PEP as a
reference integration only (`GET /authz/check`) — there is no live
`services/authz` HTTP service; `services/authz` remains scaffolded. See
`docs/engineering/sprint-4-design.md`, `services/identity/README.md`, and
`SPRINT-4-STATUS.md`.

**Sprint 5** (EPIC-03 Authorization Completion, FEAT-03-3 + FEAT-03-4 —
complete): completing the authorization baseline — a governed RBAC baseline
role catalog (`libs/python/emg-policy-engine`'s `ROLE_CATALOG`, a versioned
role vocabulary the ABAC engine's `required_roles` conditions draw from, not
a second enforcement mechanism) and a reusable authorization testing harness
(`AuthorizationScenario`, `assert_scenario`, `run_scenarios`) proven by real
adoption in `services/identity`. See `docs/engineering/sprint-5-design.md`
and `SPRINT-5-STATUS.md`.

**Sprint 6** (EPIC-04 Audit Platform, FEAT-04-1 — complete, pending merge):
the Audit Event Pipeline — a library-first core (`libs/python/emg-audit-client`
contract and `libs/python/emg-audit-pipeline` implementation: `AuditEvent`
model, append-only store, centralized hash chain and sequence assignment,
integrity verification, event-id idempotency) with `services/audit` activated
as a minimal live service that owns the append-only PostgreSQL store,
authenticated ingestion, minimal US-04 query (by actor, time range,
correlation id), and integrity verification. `services/identity` migrates from
`StructuredLogAuditSink` to a Protocol-preserving `PipelineAuditSink` with a
durable degraded-mode spool, so existing login/authentication behavior is
never coupled to the audit service's availability. FEAT-04-1 was rescheduled
from the Backlog's Sprint 5 row into Sprint 6, and FEAT-04-2/04-3/04-4 are
correspondingly shifted to later Audit sprints (engineering sequencing only —
see `docs/engineering/sprint-6-design.md` and `ARCHITECTURE_STATUS.md`).

No business logic beyond Module 4 (Identity), Module 5 (Authorization
PEP/ABAC/RBAC), and Module 6's FEAT-04-1 audit pipeline exists yet — no
Knowledge Graph, no AI orchestration, and no frontend code. Those land in
later sprints per `docs/architecture/EMG_Engineering_Backlog_v1.0.md`,
Section 6 (Sprint Planning). FEAT-04-2, FEAT-04-3, FEAT-04-4, and Sprint 7
have not been started.

## Repository Structure

Per Engineering Master Plan §3 (Monorepo Structure), operationalizing Module 1
— Repository Structure (frozen):

```
/apps            Deployable applications: web client + BFF layers (ADR-014).
                  Scaffolded only; implementation begins EPIC-10 (Sprint 21+).
/services        One directory per backend module (Modules 4–10).
                  identity/ implemented (Sprint 2 FEAT-02-1/02-2, Sprint 3
                  FEAT-02-3/02-4, Sprint 4 FEAT-03-1/03-2 reference PEP
                  integration); audit/ activated Sprint 6 (FEAT-04-1 Audit
                  Event Pipeline — minimal live service over the shared
                  audit libraries); authz/ remains scaffolded by design
                  (Module 5 is library-first, no live authorization
                  service); all other services remain scaffolded until
                  their sprint lands.
/libs             Shared libraries (Module 3, ADR-012). FEAT-01-2 scaffold,
                  extended Sprint 4 with the PEP contract
                  (emg-auth-client) and the ABAC policy engine
                  (emg-policy-engine), Sprint 5 with the RBAC baseline
                  role catalog and authorization testing harness
                  (emg-policy-engine), and Sprint 6 with the audit event
                  contract (emg-audit-client) and pipeline
                  (emg-audit-pipeline).
/infra            Infrastructure-as-code, per environment tier. Folder
                  structure only this sprint; IaC content lands EPIC-11.
/observability    Shared dashboards and alerting definitions (ADR-015).
                  Folder structure only this sprint; content lands EPIC-12.
/docs             Reference copy of the frozen Architecture Baseline v1.0
                  document set, plus engineering process documentation.
/tools            Internal developer tooling: scaffolding generators, local
                  environment scripts, CI helper scripts.
```

## Governing Documents

- `docs/architecture/EMG_Architecture_Baseline_v1.0_Final.md` — frozen architecture of record
- `docs/architecture/EMG_Engineering_Master_Plan.md` — build execution plan
- `docs/architecture/EMG_Engineering_Backlog_v1.0.md` — sprint-by-sprint backlog
- `docs/architecture/EMG_ADR-016_Enterprise_Ownership_Registry.md` — ownership registry (source for CODEOWNERS)
- `docs/architecture/EMG_ADR-015_Unified_Enterprise_Observability.md` — observability model
- `docs/architecture/EMG_ADR-017_Enterprise_Capacity_Scalability_Model.md` — capacity/HA/DR model

## Getting Started (Local Development)

See `docs/engineering/onboarding.md`. Quick start:

```bash
make bootstrap   # installs pre-commit hooks, brings up local infra containers
make up          # start local orchestration (Postgres, Redis, Keycloak, Neo4j, Qdrant)
make down        # stop local orchestration
```

## Contributing

See `CONTRIBUTING.md`. All changes are reviewed per `CODEOWNERS`
(ADR-016-derived) and must pass the CI pipeline (`.github/workflows/ci.yml`)
before merge. Direct pushes to `main` are blocked (see `.github/settings.yml`).

## Classification

Internal — Engineering Delivery. See `NOTICE.md` for classification-handling
guidance.
