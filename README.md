# EMG™ — Enterprise Memory Graph Core Platform

Monorepo for the EMG™ Core Platform, implementing **Architecture Baseline v1.0**
(Product Vision through ADR-017, frozen) under the **Engineering Master Plan**
and **Engineering Backlog v1.0**.

## Status

| Phase | Status |
| --- | --- |
| Architecture Phase | Closed — Architecture Baseline v1.0 frozen |
| Engineering Phase | Active — Sprint 4 (EPIC-03 Authorization Platform, in progress) |

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

**Sprint 4** (EPIC-03 Authorization Platform, FEAT-03-1 + FEAT-03-2 — in
progress): a library-first Policy Enforcement Point and ABAC policy engine —
`libs/python/emg-auth-client`'s `PolicyEnforcementPoint` contract and
`Decision`/`AuthorizationRequest` types, and the new
`libs/python/emg-policy-engine` package (default-deny, fail-closed,
deny-overrides evaluation, supporting both human `Principal` and machine
`ServicePrincipal` callers). `services/identity` wires the PEP as a
reference integration only (`GET /authz/check`) — there is no live
`services/authz` HTTP service this sprint; `services/authz` remains
scaffolded. See `docs/engineering/sprint-4-design.md`,
`services/identity/README.md`, and `SPRINT-4-STATUS.md`.

No business logic beyond Module 4 (Identity) and Module 5's PEP/ABAC library
scope above, no other API implementations, no AI orchestration, no Knowledge
Graph implementation, and no frontend code exists yet. Those land in later
sprints per `docs/architecture/EMG_Engineering_Backlog_v1.0.md`, Section 6
(Sprint Planning). Sprint 5 has not been started.

## Repository Structure

Per Engineering Master Plan §3 (Monorepo Structure), operationalizing Module 1
— Repository Structure (frozen):

```
/apps            Deployable applications: web client + BFF layers (ADR-014).
                  Scaffolded only; implementation begins EPIC-10 (Sprint 21+).
/services        One directory per backend module (Modules 4–10).
                  identity/ implemented (Sprint 2 FEAT-02-1/02-2, Sprint 3
                  FEAT-02-3/02-4, Sprint 4 FEAT-03-1/03-2 reference PEP
                  integration); authz/ remains scaffolded by design (Sprint
                  4 is library-first, no live authorization service); all
                  other services remain scaffolded until their sprint lands.
/libs             Shared libraries (Module 3, ADR-012). FEAT-01-2 scaffold,
                  extended Sprint 4 with the PEP contract
                  (emg-auth-client) and the ABAC policy engine
                  (emg-policy-engine).
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
